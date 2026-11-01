"""Lichess hesap bağlama (PKCE): ağ taklit edilir; akış, güvenlik ve uygunluk kuralları."""
import base64
import hashlib
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from chessdex.api import accounts
from chessdex.api import app as app_mod
from chessdex.api.engine import Engine
from chessdex.bank.models import BankItem

MATE1 = "6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1"
ACCOUNT = {"id": "oyuncu", "username": "Oyuncu",
           "perfs": {"rapid": {"games": 412, "rating": 1734, "rd": 52, "prog": 8}}}


class FakeLichess:
    def __init__(self, token_status=200, account=ACCOUNT, account_status=200):
        self.calls = []
        self.token_status, self.account, self.account_status = token_status, account, account_status

    def __call__(self, method, url, form=None, headers=None):
        self.calls.append((method, url, form, headers))
        if url.endswith("/api/token") and method == "POST":
            return (200, {"access_token": "lio_x", "token_type": "Bearer"}) if self.token_status == 200 \
                else (self.token_status, {"error": "invalid_grant"})
        if url.endswith("/api/account"):
            return self.account_status, self.account
        if url.endswith("/api/token") and method == "DELETE":
            return 204, {}
        raise AssertionError(url)


@pytest.fixture()
def eng(monkeypatch):
    e = Engine(bank=[BankItem(id=f"m{i}", source="t", fen=MATE1, solution=["a1a8"], puzzle_rating=r)
                     for i, r in enumerate(range(600, 2600, 100))])
    monkeypatch.setattr(app_mod, "engine", lambda: e)
    return e


def state_and_challenge(url):
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    return q["state"], q["code_challenge"], q


def test_pkce_pair_and_authorize_url(monkeypatch):
    verifier, challenge = accounts.pkce_pair()
    assert 43 <= len(verifier) <= 128
    assert challenge == base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    monkeypatch.setenv("CHESSDEX_PUBLIC_API_URL", "https://api.ornek.test/")
    _, _, q = state_and_challenge(accounts.authorize_url("st", challenge))
    assert q["code_challenge_method"] == "S256" and q["response_type"] == "code"
    assert q["redirect_uri"] == "https://api.ornek.test/oauth/lichess/callback" and "scope" not in q


@pytest.mark.parametrize("rapid,ok", [
    ({"games": 412, "rating": 1734, "rd": 52}, True),
    ({"games": 412, "rating": 1734, "rd": 80}, False),            # RD yüksek
    ({"games": 12, "rating": 1734, "rd": 52}, False),             # az oyun
    ({"games": 412, "rating": 1500, "rd": 52, "prov": True}, False),
    ({}, False),
])
def test_eligibility(rapid, ok):
    assert accounts.eligibility(rapid)[0] is ok


def test_exchange_revokes_token_even_on_failure():
    fake = FakeLichess(account_status=500)
    with pytest.raises(ValueError):
        accounts.exchange_and_fetch("kod", "v" * 50, fake)
    assert fake.calls[-1][0] == "DELETE"                             # belirteç her durumda iptal edildi
    with pytest.raises(ValueError):
        accounts.exchange_and_fetch("kod", "v" * 50, FakeLichess(token_status=400))


def test_engine_link_flow_and_report(eng):
    s = eng.create("short")
    url = eng.link_start(s)
    state, challenge, _ = state_and_challenge(url)
    verifier = s.oauth["verifier"]
    assert challenge == base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    fake = FakeLichess()
    eng.link_callback("kod", state, fake)
    post = fake.calls[0]
    assert post[2]["code_verifier"] == verifier and post[2]["code"] == "kod"
    assert s.oauth is None and s.external["username"] == "Oyuncu" and s.external["calibration_eligible"]
    assert "lio_x" not in repr(s.external)                           # belirteç saklanmaz
    with pytest.raises(KeyError):                                    # aynı state ikinci kez kullanılamaz
        eng.link_callback("kod", state, fake)
    while not eng.next_item(s)["done"]:
        eng.respond(s, eng.next_item(s)["item"]["token"], ["a1a8"], 1000)
    rep = eng.report(s)
    assert rep["external"]["rating"] == 1734
    assert rep["comparison"]["verified_rating"] == 1734 and "inside_90" in rep["comparison"]


def test_expired_state_rejected(eng):
    s = eng.create("short")
    state, _, _ = state_and_challenge(eng.link_start(s))
    s.oauth["created"] -= accounts.STATE_TTL_S + 1
    with pytest.raises(ValueError):
        eng.link_callback("kod", state, FakeLichess())
    assert s.external is None


def test_api_endpoints_redirect(eng, monkeypatch):
    monkeypatch.setenv("CHESSDEX_WEB_URL", "http://web.test")
    monkeypatch.setattr(accounts, "default_fetch", FakeLichess())
    c = TestClient(app_mod.app)
    sid = c.post("/sessions", json={"mode": "short"}).json()["session_id"]
    url = c.post(f"/sessions/{sid}/link/lichess").json()["authorize_url"]
    assert url.startswith("https://lichess.org/oauth?")
    state, _, _ = state_and_challenge(url)
    r = c.get("/oauth/lichess/callback", params={"state": state, "code": "kod"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"http://web.test/report/{sid}?link=ok"
    assert eng.get(sid).external["rating"] == 1734
    # bilinmeyen/yeniden kullanılan state ve kullanıcı reddi
    r = c.get("/oauth/lichess/callback", params={"state": state, "code": "kod"}, follow_redirects=False)
    assert r.headers["location"] == "http://web.test/?link=expired"
    sid2 = c.post("/sessions", json={"mode": "short"}).json()["session_id"]
    st2, _, _ = state_and_challenge(c.post(f"/sessions/{sid2}/link/lichess").json()["authorize_url"])
    r = c.get("/oauth/lichess/callback", params={"state": st2, "error": "access_denied"}, follow_redirects=False)
    assert r.headers["location"] == f"http://web.test/report/{sid2}?link=denied" and eng.get(sid2).oauth is None
