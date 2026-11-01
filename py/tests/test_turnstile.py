"""Cloudflare Turnstile: yapılandırılmamışken kapalı; yapılandırılınca oturum oluşturma geçerli belirteç ister."""
import pytest
from fastapi.testclient import TestClient

from chessdex.api import accounts
from chessdex.api import app as app_mod
from chessdex.api.engine import Engine
from chessdex.bank.models import BankItem

MATE1 = "6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1"


@pytest.fixture()
def client(monkeypatch):
    e = Engine(bank=[BankItem(id="m", source="t", fen=MATE1, solution=["a1a8"], puzzle_rating=1500)])
    monkeypatch.setattr(app_mod, "engine", lambda: e)
    return TestClient(app_mod.app)


def fake_verify(success):
    calls = []

    def fetch(method, url, form=None, headers=None):
        calls.append(form)
        return 200, {"success": success}
    fetch.calls = calls
    return fetch


def test_disabled_without_secret(client, monkeypatch):
    monkeypatch.delenv("CHESSDEX_TURNSTILE_SECRET", raising=False)
    assert client.post("/sessions", json={"mode": "short"}).status_code == 200
    assert client.get("/health").json()["turnstile"] is False


def test_required_when_configured(client, monkeypatch):
    monkeypatch.setenv("CHESSDEX_TURNSTILE_SECRET", "gizli")
    monkeypatch.setattr(accounts, "default_fetch", fake_verify(True))
    assert client.post("/sessions", json={"mode": "short"}).status_code == 403                 # belirteç yok
    ok = client.post("/sessions", json={"mode": "short", "turnstile_token": "tok"})
    assert ok.status_code == 200
    assert accounts.default_fetch.calls[-1]["secret"] == "gizli" and accounts.default_fetch.calls[-1]["response"] == "tok"
    monkeypatch.setattr(accounts, "default_fetch", fake_verify(False))
    assert client.post("/sessions", json={"mode": "short", "turnstile_token": "tok"}).status_code == 403


def test_network_failure_rejects(monkeypatch):
    monkeypatch.setenv("CHESSDEX_TURNSTILE_SECRET", "gizli")

    def boom(*a, **k):
        raise OSError("ağ yok")
    assert accounts.turnstile_ok("tok", None, boom) is False
