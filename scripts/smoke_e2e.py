"""Uçtan uca duman testi: API (8000) ve oyun sunucusu (8080) çalışırken tam bir oturum oynar.

Kullanım: .venv/Scripts/python scripts/smoke_e2e.py
"""
import asyncio
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request

import chess
import websockets

API = os.environ.get("CHESSDEX_API_URL", "http://localhost:8000")
WS = os.environ.get("CHESSDEX_WS_URL", "ws://localhost:8080/ws")


def call(method, path, body=None):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


async def play(sid, g, max_user_moves=25):
    rng = random.Random(0)
    async with websockets.connect(WS) as ws:
        await ws.send(json.dumps({"t": "join", "session_id": sid, "game_id": g["game_id"],
                                  "user_color": g["user_color"], "time_control": g["time_control"]}))
        sent, acted = 0, set()
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
            if msg["t"] == "end":
                return msg
            if msg["t"] in ("state", "move"):
                board = chess.Board(msg["fen"])
                mine = (board.turn == chess.WHITE) == (g["user_color"] == "white")
                if mine and not board.is_game_over() and msg["fen"] not in acted:
                    acted.add(msg["fen"])
                    if sent >= max_user_moves:
                        await ws.send(json.dumps({"t": "resign"}))
                        continue
                    await ws.send(json.dumps({"t": "move", "uci": rng.choice(list(board.legal_moves)).uci()}))
                    sent += 1
            elif msg["t"] in ("illegal", "error"):
                print("uyarı:", msg)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("health:", call("GET", "/health"))
    sid = call("POST", "/sessions", {"mode": "full"})["session_id"]
    n = 0
    while True:
        r = call("GET", f"/sessions/{sid}/next-item")
        if r["done"]:
            break
        it = r["item"]
        mv = (it.get("choices") or [m.uci() for m in chess.Board(it["fen"]).legal_moves])[0]
        res = call("POST", f"/sessions/{sid}/responses", {"token": it["token"], "moves": [mv], "elapsed_ms": 5000})
        n += 1
    print(f"senaryo: {n}, tahmin: {res['estimate']}")
    g = call("POST", f"/sessions/{sid}/game")
    print("oyun:", g)
    end = asyncio.run(play(sid, g))
    print("bitiş:", end)
    for _ in range(30):
        try:
            rep = call("GET", f"/sessions/{sid}/report")
            break
        except urllib.error.HTTPError:
            time.sleep(1)
    else:
        sys.exit("rapor alınamadı")
    print(json.dumps({k: rep[k] for k in ("estimate", "scales", "flags", "match_used", "critical_moments")},
                     indent=1, ensure_ascii=False))
    est = rep["estimate"]
    checks = {
        "oyun bitti mesajı": end.get("t") == "end",
        "rapor tamamlandı": est["stage"] == "done",
        "aralık tutarlı": est["lo90"] <= est["median"] <= est["hi90"],
        "üç skala": set(rep["scales"]) == {"lichess", "chesscom", "fide"},
        "model sürümü": "measure" in rep["model_version"],
    }
    for name, ok in checks.items():
        print(("GEÇTİ " if ok else "KALDI ") + name)
    if not all(checks.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
