"""Chess.com profil koduyla sahiplik doğrulaması (ağ taklit edilir)."""
import pytest
from fastapi.testclient import TestClient

from chessdex.api import accounts
from chessdex.api import app as app_mod
from chessdex.api.engine import Engine
from chessdex.bank.models import BankItem

MATE1 = "6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1"


def fake_chesscom(location="", status=200, rapid=None):
    rapid = rapid if rapid is not None else {"last": {"rating": 1450, "rd": 40}, "record": {"win": 60, "loss": 50, "draw": 5}}
    calls = []

    def fetch(method, url, form=None, headers=None):
        calls.append((method, url, headers))
        assert headers and "User-Agent" in headers                   # Chess.com UA ister
        if url.endswith("/stats"):
            return 200, {"chess_rapid": rapid}
        return (status, {"username": "Oyuncu", "location": location, "name": None}) if status == 200 else (status, {})
    fetch.calls = calls
    return fetch


@pytest.fixture()
def eng(monkeypatch):
    e = Engine(bank=[BankItem(id=f"m{i}", source="t", fen=MATE1, solution=["a1a8"], puzzle_rating=r)
                     for i, r in enumerate(range(600, 2600, 100))])
    monkeypatch.setattr(app_mod, "engine", lambda: e)
    return e


def test_code_format():
    c = accounts.chesscom_code()
    assert c.startswith("chessdex-") and len(c) == 15 and not set(c[9:]) & set("01IO")


def test_verify_success_and_failures():
    rec = accounts.chesscom_verify("Oyuncu", "chessdex-ABC234", fake_chesscom(location="İstanbul chessdex-abc234"))
    assert rec["platform"] == "chesscom" and rec["rating"] == 1450 and rec["games"] == 115 and rec["calibration_eligible"]
    with pytest.raises(ValueError, match="Kod profilin"):
        accounts.chesscom_verify("Oyuncu", "chessdex-ABC234", fake_chesscom(location="İstanbul"))
    with pytest.raises(ValueError, match="bulunamadı"):
        accounts.chesscom_verify("yok", "chessdex-ABC234", fake_chesscom(status=404))
    low = accounts.chesscom_verify("Oyuncu", "chessdex-X", fake_chesscom(location="chessdex-X",
                                   rapid={"last": {"rating": 900, "rd": 120}, "record": {"win": 3, "loss": 2, "draw": 0}}))
    assert not low["calibration_eligible"] and len(low["ineligible_reasons"]) == 2
    none = accounts.chesscom_verify("Oyuncu", "chessdex-X", fake_chesscom(location="chessdex-X", rapid={}))
    assert none["rating"] is None and not none["calibration_eligible"]


def test_engine_flow_comparison_uses_chesscom_scale(eng):
    s = eng.create("short")
    code = eng.chesscom_start(s, "Oyuncu")
    with pytest.raises(ValueError):
        eng.chesscom_verify(s, fake_chesscom(location="başka"))
    eng.chesscom_verify(s, fake_chesscom(location=code))
    assert s.oauth is None and s.external["verified_by"] == "profile_code"
    while not eng.next_item(s)["done"]:
        eng.respond(s, eng.next_item(s)["item"]["token"], ["a1a8"], 1000)
    rep = eng.report(s)
    assert rep["comparison"]["scale"] == "chesscom"
    assert rep["comparison"]["difference"] == rep["scales"]["chesscom"]["median"] - 1450


def test_code_expiry(eng):
    s = eng.create("short")
    code = eng.chesscom_start(s, "Oyuncu")
    s.oauth["created"] -= accounts.CODE_TTL_S + 1
    with pytest.raises(ValueError, match="süresi"):
        eng.chesscom_verify(s, fake_chesscom(location=code))


def test_api_endpoints(eng, monkeypatch):
    c = TestClient(app_mod.app)
    sid = c.post("/sessions", json={"mode": "short"}).json()["session_id"]
    assert c.post(f"/sessions/{sid}/link/chesscom", json={"username": "a b"}).status_code == 422
    assert c.post(f"/sessions/{sid}/link/chesscom/verify").status_code == 409          # önce kod alınmalı
    code = c.post(f"/sessions/{sid}/link/chesscom", json={"username": "Oyuncu"}).json()["code"]
    monkeypatch.setattr(accounts, "default_fetch", fake_chesscom(location=code))
    r = c.post(f"/sessions/{sid}/link/chesscom/verify")
    assert r.status_code == 200 and r.json()["external"]["rating"] == 1450
