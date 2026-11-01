import chess
import pytest
from fastapi.testclient import TestClient

from chessdex.api import app as app_mod
from chessdex.api.engine import Engine
from chessdex.bank.models import BankItem

MATE1 = "6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1"


def tiny_bank():
    items = []
    for i, r in enumerate(range(500, 2900, 40)):
        kind = ["tactics", "endgame", "defense"][i % 3]
        items.append(BankItem(id=f"m{i}", source="test", fen=MATE1, solution=["a1a8"], kind=kind, puzzle_rating=r))
        items.append(BankItem(id=f"p{i}", source="test", fen=MATE1, solution=["a1a8"], kind="positional",
                              puzzle_rating=r, choices=["a1a8", "g1f1", "a1a2", "g1h1"],
                              move_scores={"a1a8": 3, "g1f1": 1, "a1a2": 2, "g1h1": 0}))
    return items


class NoEngine:
    """Stockfish yokmuş gibi davranır: birleştirme mantığı motordan bağımsız sınanır."""
    available = False

    def analyse(self, fen):
        return None

    def win_prob_loss(self, fen, move):
        return None


@pytest.fixture(autouse=True)
def deterministic_ids(monkeypatch):
    """Oturum/oyun kimlikleri bot tohumunu belirler; testlerin her çalıştırmada aynı oyunu oynaması için sayaç."""
    import itertools

    from chessdex.api import engine as engine_mod
    counter = itertools.count()
    monkeypatch.setattr(engine_mod.secrets, "token_urlsafe", lambda n=16: f"t{next(counter):06d}")


@pytest.fixture()
def client(monkeypatch):
    eng = Engine(bank=tiny_bank())
    eng.analyzer = NoEngine()
    monkeypatch.setattr(app_mod, "engine", lambda: eng)
    return TestClient(app_mod.app)


def answer(item):
    """Dönüştürülmüş pozisyonda mat eden hamleyi bul."""
    b = chess.Board(item["fen"])
    if item.get("choices"):
        for u in item["choices"]:
            b2 = b.copy(); b2.push_uci(u)
            if b2.is_checkmate():
                return u
    for m in b.legal_moves:
        b2 = b.copy(); b2.push(m)
        if b2.is_checkmate():
            return m.uci()
    raise AssertionError("mat yok")


def run_items(client, sid, correct=True):
    n = 0
    while True:
        r = client.get(f"/sessions/{sid}/next-item").json()
        if r["done"]:
            return n
        item = r["item"]
        assert "id" not in item and "a1a8" not in str(item.get("token"))
        good = answer(item)
        opts = item.get("choices") or [m.uci() for m in chess.Board(item["fen"]).legal_moves]
        mv = good if correct else next(u for u in opts if u != good)
        res = client.post(f"/sessions/{sid}/responses", json={"token": item["token"], "moves": [mv], "elapsed_ms": 3000}).json()
        assert res["correct"] == correct
        n += 1


def test_health(client):
    assert client.get("/health").json()["ok"]


def test_short_session_all_correct_is_high(client):
    sid = client.post("/sessions", json={"mode": "short"}).json()["session_id"]
    n = run_items(client, sid)
    assert 12 <= n <= 20
    rep = client.get(f"/sessions/{sid}/report").json()
    assert rep["estimate"]["median"] > 1800
    assert rep["estimate"]["lo90"] <= rep["estimate"]["median"] <= rep["estimate"]["hi90"]
    assert set(rep["scales"]) == {"lichess", "chesscom", "fide"}


def test_bad_token(client):
    sid = client.post("/sessions", json={"mode": "short"}).json()["session_id"]
    client.get(f"/sessions/{sid}/next-item")
    assert client.post(f"/sessions/{sid}/responses", json={"token": "x", "moves": []}).status_code == 409


def play_full_session(client, realistic=False):
    """realistic=True: kullanıcı da insan-hamle modelinden örneklenen hamleler oynar (oyun erken bitmez);
    False: sıralı listeden anlamsız hamleler (oyun hızla 'bitmiş' pozisyona gider)."""
    sid = client.post("/sessions", json={"mode": "full"}).json()["session_id"]
    run_items(client, sid, correct=False)
    assert client.get(f"/sessions/{sid}/report").status_code == 409
    g = client.post(f"/sessions/{sid}/game").json()
    gid, color = g["game_id"], g["user_color"]
    board = chess.Board()
    ply = 0
    while not board.is_game_over() and ply < 80:
        fen = board.fen()
        if (board.turn == chess.WHITE) == (color == "white"):
            if realistic:
                mv = client.post(f"/games/{gid}/bot-move", json={"fen": fen, "ply": ply}).json()["uci"]
            else:
                mv = sorted(m.uci() for m in board.legal_moves)[ply % board.legal_moves.count()]
            client.post(f"/games/{gid}/user-move", json={"ply": ply, "fen_before": fen, "uci": mv,
                                                       "spent_ms": 4000 + 100 * ply, "clock_ms": 500000})
        else:
            r = client.post(f"/games/{gid}/bot-move", json={"fen": fen, "ply": ply}).json()
            assert 1000 <= r["think_ms"] <= 8000
            mv = r["uci"]
        board.push_uci(mv)
        ply += 1
    client.post(f"/games/{gid}/finish", json={"result": "0-1" if color == "white" else "1-0", "reason": "resign"})
    return client.get(f"/sessions/{sid}/report").json()


def test_full_flow_with_game(client):
    rep = play_full_session(client, realistic=True)
    game = next(iter(app_mod.engine().games.values())).game
    n_full = sum(1 for m in game.moves if m.get("weight", 0) >= 1.0)
    assert rep["match_used"] == (n_full >= 15)
    assert n_full >= 15, f"gerçekçi oyunda yalnızca {n_full} tam ağırlıklı hamle"
    assert len(rep["critical_moments"]) <= 3
    assert rep["estimate"]["stage"] == "done"


def test_determinism_of_bot(client):
    sid = client.post("/sessions", json={"mode": "full"}).json()["session_id"]
    run_items(client, sid)
    gid = client.post(f"/sessions/{sid}/game").json()["game_id"]
    a = client.post(f"/games/{gid}/bot-move", json={"fen": chess.STARTING_FEN, "ply": 0}).json()
    b = client.post(f"/games/{gid}/bot-move", json={"fen": chess.STARTING_FEN, "ply": 0}).json()
    assert a == b


def test_multi_move_partial_flow(monkeypatch):
    line = ["e2e4", "e7e5", "g1f3"]
    bank = [BankItem(id=f"l{i}", source="test", fen=chess.STARTING_FEN, solution=line, puzzle_rating=r)
            for i, r in enumerate(range(800, 2400, 100))]
    eng = Engine(bank=bank)
    monkeypatch.setattr(app_mod, "engine", lambda: eng)
    c = TestClient(app_mod.app)
    sid = c.post("/sessions", json={"mode": "short"}).json()["session_id"]
    item = c.get(f"/sessions/{sid}/next-item").json()["item"]
    assert item["n_moves"] == 3  # tam çizgi (yarım hamle)
    # dönüşüm (renk takası/ayna) sonrası ilk doğru hamleyi bul: başlangıç pozisyonunda rok hakkı var → yalnızca kimlik/renk takası
    sol = eng.sessions[sid].pending.item.solution
    r = c.post(f"/sessions/{sid}/responses", json={"token": item["token"], "moves": [sol[0]], "partial": True}).json()
    assert r == {"continue": True, "reply": sol[1]}
    r = c.post(f"/sessions/{sid}/responses", json={"token": item["token"], "moves": sol}).json()
    assert r["correct"] is True
    # yanlış ilk hamle → nihai yanlış yanıt
    item = c.get(f"/sessions/{sid}/next-item").json()["item"]
    r = c.post(f"/sessions/{sid}/responses", json={"token": item["token"], "moves": ["a2a3"], "partial": True}).json()
    assert r["correct"] is False and "continue" not in r


def test_full_flow_with_real_stockfish(monkeypatch):
    """Gerçek motorla: anlamsız hamleler oyunu hızla 'bitmiş' (|eval| > 5 piyon) yapar → hamleler düşük ağırlık alır.
    Tam ağırlıklı hamle < 15 ise maç sinyali kullanılmamalı ve sonuç 'short_game' olarak işaretlenmeli."""
    from chessdex.engines.stockfish import Analyzer
    sf = Analyzer(nodes=20_000)
    if not sf.available:
        pytest.skip("Stockfish kurulu değil")
    eng = Engine(bank=tiny_bank())
    eng.analyzer = sf
    monkeypatch.setattr(app_mod, "engine", lambda: eng)
    rep = play_full_session(TestClient(app_mod.app))
    game = next(iter(eng.games.values())).game
    assert all("eval_cp" in m for m in game.moves)
    assert any(m["reason"] == "decided" for m in game.moves)
    assert rep["match_used"] or "short_game" in rep["flags"]
    assert all(c["source"] == "stockfish" for c in rep["critical_moments"])
    sf.close()


def test_short_mode_stops_on_server_time_budget(monkeypatch):
    """Kısa mod ≤ 8 dk: sunucu saatine göre her cevap 60 sn sürerse 6,5 dk bütçe 7. senaryodan sonra biter."""
    from chessdex.api import engine as engine_mod
    from chessdex.measure.stopping import SHORT_BUDGET_MS

    clock = {"t": 1000.0}
    monkeypatch.setattr(engine_mod.time, "time", lambda: clock["t"])
    eng = Engine(bank=tiny_bank())
    eng.analyzer = NoEngine()
    s = eng.create("short")
    n = 0
    while True:
        r = eng.next_item(s)
        if r["done"]:
            break
        it = r["item"]
        assert it["time_budget_ms"] == int(SHORT_BUDGET_MS) and it["spent_ms"] == n * 60_000
        clock["t"] += 60.0
        eng.respond(s, it["token"], ["g1f1"], 60_000)      # yanlış cevap: sd küçülmez, yalnız bütçe durdurur
        n += 1
    assert n == 7 and s.stage == "done"


def test_full_mode_item_has_no_time_budget():
    eng = Engine(bank=tiny_bank())
    eng.analyzer = NoEngine()
    it = eng.next_item(eng.create("full"))["item"]
    assert "time_budget_ms" not in it


def test_focus_lost_reaches_integrity_signal(monkeypatch):
    """focus_lost user-move gövdesinden kayda ve bütünlük satırlarına gider; gövdede yoksa False."""
    eng = Engine(bank=tiny_bank())
    eng.analyzer = NoEngine()
    s = eng.create("full")
    while not eng.next_item(s)["done"]:
        it = eng.next_item(s)["item"]
        eng.respond(s, it["token"], ["a1a8"], 5000)
    g = eng.start_game(s)
    board = chess.Board()
    ply, n_user = 0, 0
    for _ in range(12):
        uci = next(iter(board.legal_moves)).uci()
        if (board.turn == chess.WHITE) == (g.user_color == "white"):
            eng.user_move(g.id, ply, board.fen(), uci, 2000, 500_000, focus_lost=(n_user % 2 == 0))
            n_user += 1
        board.push_uci(uci)
        ply += 1
    for f in g.futures:
        f.result()
    flags = [m["focus_lost"] for m in g.moves]
    assert any(flags) and not all(flags)
    seen = {}
    monkeypatch.setattr("chessdex.api.engine.integrity_score", lambda rows: seen.setdefault("rows", rows) and
                        {"score": 0, "reasons": [], "flag": False, "signals": {}})
    eng._integrity(s, 1500)
    assert [r["focus_lost"] for r in seen["rows"]] == flags


def test_user_move_body_focus_lost_optional(client):
    sid = client.post("/sessions", json={"mode": "full"}).json()["session_id"]
    run_items(client, sid)
    gid = client.post(f"/sessions/{sid}/game").json()["game_id"]
    body = {"ply": 0, "fen_before": chess.STARTING_FEN, "uci": "e2e4", "spent_ms": 100, "clock_ms": 600000}
    assert client.post(f"/games/{gid}/user-move", json=body).status_code == 200
    assert client.post(f"/games/{gid}/user-move", json={**body, "ply": 2, "focus_lost": True}).status_code == 200
    assert client.post(f"/games/{gid}/user-move", json={**body, "ply": 4, "focus_lost": "belki"}).status_code == 422
