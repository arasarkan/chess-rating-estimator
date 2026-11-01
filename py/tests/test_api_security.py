"""API güvenlik ve sağlamlık: iç belirteç, girdi doğrulama, hız sınırı, oturum temizliği."""
import chess
import pytest
from fastapi.testclient import TestClient

from chessdex.api import app as app_mod
from chessdex.api import engine as engine_mod
from chessdex.api.engine import Engine
from chessdex.bank.models import BankItem

MATE1 = "6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1"


class NoEngine:
    available = False
    nodes = 0

    def analyse(self, fen):
        return None


@pytest.fixture()
def eng(monkeypatch):
    e = Engine(bank=[BankItem(id=f"m{i}", source="t", fen=MATE1, solution=["a1a8"], puzzle_rating=r)
                     for i, r in enumerate(range(600, 2600, 50))])
    e.analyzer = NoEngine()
    monkeypatch.setattr(app_mod, "engine", lambda: e)
    app_mod.session_limiter._b.clear()
    return e


def started_game(c):
    sid = c.post("/sessions", json={"mode": "full"}).json()["session_id"]
    while not c.get(f"/sessions/{sid}/next-item").json()["done"]:
        it = c.get(f"/sessions/{sid}/next-item").json()["item"]
        c.post(f"/sessions/{sid}/responses", json={"token": it["token"], "moves": ["a1a8"], "elapsed_ms": 1000})
    return c.post(f"/sessions/{sid}/game").json()["game_id"]


def test_internal_endpoints_require_token(eng, monkeypatch):
    monkeypatch.setenv("CHESSDEX_INTERNAL_TOKEN", "s3cret")
    c = TestClient(app_mod.app)
    gid = started_game(c)
    body = {"fen": chess.STARTING_FEN, "ply": 0}
    assert c.post(f"/games/{gid}/bot-move", json=body).status_code == 403
    assert c.post(f"/games/{gid}/bot-move", json=body, headers={"x-internal-token": "yanlis"}).status_code == 403
    assert c.post(f"/games/{gid}/bot-move", json=body, headers={"x-internal-token": "s3cret"}).status_code == 200
    um = {"ply": 0, "fen_before": chess.STARTING_FEN, "uci": "e2e4", "spent_ms": 1, "clock_ms": 1}
    assert c.post(f"/games/{gid}/user-move", json=um).status_code == 403
    assert c.post(f"/games/{gid}/finish", json={"result": "1-0", "reason": "x"}).status_code == 403
    assert c.get("/health").json()["internal_auth"] is True
    # kullanıcıya açık uçlar belirteç istemez
    assert c.post("/sessions", json={"mode": "short"}).status_code == 200


def test_production_requires_token(monkeypatch):
    monkeypatch.setenv("CHESSDEX_ENV", "production")
    monkeypatch.delenv("CHESSDEX_INTERNAL_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        app_mod.check_config()
    monkeypatch.setenv("CHESSDEX_INTERNAL_TOKEN", "x")
    app_mod.check_config()


@pytest.mark.parametrize("body", [
    {"token": "t", "moves": ["e2e9"]},                      # geçersiz UCI
    {"token": "t", "moves": ["e2e4"] * 21},                  # çok uzun
    {"token": "", "moves": []},                              # boş token
    {"token": "t", "moves": [], "elapsed_ms": -5},           # negatif süre
])
def test_response_validation(eng, body):
    c = TestClient(app_mod.app)
    sid = c.post("/sessions", json={"mode": "short"}).json()["session_id"]
    assert c.post(f"/sessions/{sid}/responses", json=body).status_code == 422


def test_survey_and_path_validation(eng):
    c = TestClient(app_mod.app)
    assert c.post("/sessions", json={"survey": {"hack": "1"}}).status_code == 422
    assert c.post("/sessions", json={"survey": {"years_playing": "gt10"}}).status_code == 200
    assert c.post("/sessions", json={"survey": {"years_playing": "çok"}}).status_code == 422
    assert c.post("/sessions", json={"mode": "blitz"}).status_code == 422
    assert c.get("/sessions/a%2F..%2Fb/next-item").status_code in (404, 422)
    assert c.get("/sessions/kisa/next-item").status_code == 404


def test_bot_move_rejects_bad_fen(eng):
    c = TestClient(app_mod.app)
    gid = started_game(c)
    assert c.post(f"/games/{gid}/bot-move", json={"fen": "bozuk fen", "ply": 0}).status_code == 422
    assert c.post(f"/games/{gid}/user-move", json={"ply": 0, "fen_before": chess.STARTING_FEN, "uci": "zz",
                                                    "spent_ms": 1, "clock_ms": 1}).status_code == 422


def test_session_rate_limit(eng):
    c = TestClient(app_mod.app)
    codes = [c.post("/sessions", json={"mode": "short"}).status_code for _ in range(15)]
    assert codes[:10] == [200] * 10 and 429 in codes


def test_rate_limiter_refills():
    rl = app_mod.RateLimiter(rate=60, per=60, burst=2)
    assert rl.allow("a", 0) and rl.allow("a", 0) and not rl.allow("a", 0)
    assert rl.allow("a", 1.0)                                  # 1 sn'de 1 belirteç dolar
    assert rl.allow("b", 0)                                    # istemciler bağımsız


def test_session_ttl_and_capacity(eng, monkeypatch):
    s1 = eng.create("short")
    s2 = eng.create("full")
    eng.start_game(s2)
    s1.last_active -= engine_mod.SESSION_TTL_S + 1
    s2.last_active -= engine_mod.SESSION_TTL_S + 1
    assert eng.cleanup() == 2
    assert not eng.sessions and not eng.games
    monkeypatch.setattr(engine_mod, "MAX_SESSIONS", 3)
    made = [eng.create("short") for _ in range(5)]
    assert len(eng.sessions) == 3 and made[-1].id in eng.sessions and made[0].id not in eng.sessions


def test_not_found_message_is_clean(eng):
    c = TestClient(app_mod.app)
    r = c.get("/sessions/yokboyle/next-item")
    assert r.status_code == 404 and r.json()["detail"] == "oturum bulunamadı"


def test_critical_moments_only_meaningful_losses_with_san(eng):
    import numpy as np

    from chessdex.api.engine import Game
    from chessdex.measure.grid import GRID
    from chessdex.measure.posterior import Posterior
    from chessdex.measure.prior import default_prior
    s = eng.create("full")
    g = Game("g123", 1500, "black", 1)
    s.game = g
    s.final = Posterior(default_prior())
    after_e4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
    grid = np.full(GRID.size, 0.1)
    g.moves = [
        {"ply": 1, "fen": after_e4, "uci": "g7g5", "grid": grid, "weight": 1.0, "win_prob_loss": 0.12},
        {"ply": 1, "fen": after_e4, "uci": "a7a6", "grid": grid, "weight": 1.0, "win_prob_loss": 0.0},
    ]
    rows = eng._critical(s)
    assert [r["played"] for r in rows] == ["g7g5"]
    r = rows[0]
    assert r["played_san"] == "g5" and r["move_no"] == 1 and r["side"] == "black"
    assert r["typical_san"] and r["source"] == "stockfish"


def test_client_ip_respects_only_trusted_proxies(monkeypatch):
    from starlette.requests import Request

    def req(peer, xff=None):
        headers = [(b"x-forwarded-for", xff.encode())] if xff else []
        return Request({"type": "http", "client": (peer, 1), "headers": headers})

    monkeypatch.delenv("CHESSDEX_TRUSTED_PROXIES", raising=False)
    assert app_mod.client_ip(req("9.9.9.9", "1.1.1.1")) == "9.9.9.9"        # vekil yokken başlık yok sayılır
    monkeypatch.setenv("CHESSDEX_TRUSTED_PROXIES", "10.0.0.1, 10.0.0.2")
    assert app_mod.client_ip(req("10.0.0.1", "1.1.1.1")) == "1.1.1.1"
    assert app_mod.client_ip(req("10.0.0.1", "6.6.6.6, 1.1.1.1, 10.0.0.2")) == "1.1.1.1"   # sahte sol adres atlanmaz
    assert app_mod.client_ip(req("9.9.9.9", "1.1.1.1")) == "9.9.9.9"        # güvenilmeyen eş: başlık yok sayılır
    assert app_mod.client_ip(req("10.0.0.1")) == "10.0.0.1"
