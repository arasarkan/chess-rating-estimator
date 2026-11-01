import json

import chess

from chessdex.bank.tablebase import Prober, check_item, main, tb_key

KQK = "8/8/8/8/8/2k5/8/KQ6 w - - 0 1"
DRAWISH = "8/8/8/8/8/2k5/8/K1q4R w - - 0 1"


def fake(table):
    """table: tb_key → (kategori, {uci: hamle sonrası kategori (rakip bakışı)})."""
    calls = []

    def fetch(fen):
        calls.append(fen)
        cat, moves = table[tb_key(chess.Board(fen))]
        return {"category": cat, "moves": [{"uci": u, "category": c, "checkmate": False} for u, c in moves.items()]}

    fetch.calls = calls
    return fetch


def key(fen):
    return tb_key(chess.Board(fen))


def test_winning_move_ok_and_counts_alternatives():
    p = Prober(fetch=fake({key(KQK): ("win", {"b1e4": "loss", "b1d1": "loss", "b1b8": "draw"})}), delay_s=0)
    r = check_item(KQK, ["b1e4"], p)
    assert r["verdict"] == "ok" and r["alternatives"] == 1 and r["steps"] == 1


def test_move_that_throws_away_win_is_wrong():
    p = Prober(fetch=fake({key(KQK): ("win", {"b1e4": "loss", "b1b8": "draw"})}), delay_s=0)
    r = check_item(KQK, ["b1b8"], p)
    assert r["verdict"] == "wrong" and "win → draw" in r["reason"]


def test_draw_with_other_drawing_moves_is_ambiguous():
    p = Prober(fetch=fake({key(DRAWISH): ("draw", {"h1c1": "draw", "h1h3": "draw", "a1a2": "win"})}), delay_s=0)
    assert check_item(DRAWISH, ["h1c1"], p)["verdict"] == "ambiguous"
    p2 = Prober(fetch=fake({key(DRAWISH): ("draw", {"h1c1": "draw", "a1a2": "win"})}), delay_s=0)
    assert check_item(DRAWISH, ["h1c1"], p2)["verdict"] == "ok"


def test_many_pieces_unchecked_and_no_request():
    f = fake({})
    r = check_item(chess.STARTING_FEN, ["e2e4"], Prober(fetch=f, delay_s=0))
    assert r["verdict"] == "unchecked" and f.calls == []


def test_later_player_move_checked_after_capture():
    # 8 taş: ilk hamle sorgulanmaz; alım sonrası 7 taşta ikinci oyuncu hamlesi sorgulanır
    fen = "4k3/7p/8/3p4/4P3/8/6q1/K2R3R w - - 0 1"
    b = chess.Board(fen)
    for u in ["e4d5", "g2g6"]:
        b.push_uci(u)
    f = fake({tb_key(b): ("win", {"h1h7": "loss"})})
    r = check_item(fen, ["e4d5", "g2g6", "h1h7"], Prober(fetch=f, delay_s=0))
    assert r["verdict"] == "ok" and r["steps"] == 1 and len(f.calls) == 1


def test_cache_roundtrip_avoids_network(tmp_path):
    cache = tmp_path / "tb.json"
    f = fake({key(KQK): ("win", {"b1e4": "loss"})})
    p = Prober(cache, fetch=f, delay_s=0)
    check_item(KQK, ["b1e4"], p)
    p.save()
    f2 = fake({})
    assert check_item(KQK, ["b1e4"], Prober(cache, fetch=f2, delay_s=0))["verdict"] == "ok"
    assert f2.calls == []


def test_cli_drops_wrong_and_annotates(tmp_path, monkeypatch):
    import chessdex.bank.tablebase as tb

    monkeypatch.setattr(tb, "http_probe", fake({key(KQK): ("win", {"b1e4": "loss", "b1b8": "draw"})}))
    monkeypatch.setattr(tb.Prober.__init__, "__defaults__", (None, tb.http_probe, 0.0))
    inp, out, rep = tmp_path / "in.jsonl", tmp_path / "out.jsonl", tmp_path / "rep.json"
    rows = [{"id": "good", "fen": KQK, "solution": ["b1e4"], "kind": "endgame", "meta": {}},
            {"id": "bad", "fen": KQK, "solution": ["b1b8"], "kind": "endgame", "meta": {}},
            {"id": "big", "fen": chess.STARTING_FEN, "solution": ["e2e4"], "kind": "tactics", "meta": {}}]
    inp.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    assert main([str(inp), str(out), "--report", str(rep), "--delay", "0"]) == 0
    kept = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [r["id"] for r in kept] == ["good", "big"]
    assert kept[0]["meta"]["tablebase_verdict"] == "ok" and "tablebase_verdict" not in kept[1]["meta"]
    report = json.loads(rep.read_text(encoding="utf-8"))
    assert report["verdicts"] == {"ok": 1, "wrong": 1, "unchecked": 1}
    assert report["examples"]["wrong"][0]["id"] == "bad"
