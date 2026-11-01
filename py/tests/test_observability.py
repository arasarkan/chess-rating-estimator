"""Gözlemlenebilirlik: istek kimliği, iç ayrıntı sızdırmayan 500, JSON günlük ve Sentry'ye gerçek gönderim (yerel dinleyici)."""
import gzip
import json
import logging
import threading
import zlib
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from chessdex.api import app as app_mod
from chessdex.api import observability
from chessdex.api.engine import Engine
from chessdex.bank.models import BankItem

MATE1 = "6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1"


class Boom(Engine):
    def report(self, s):
        raise RuntimeError("gizli iç ayrıntı: veritabanı yolu C:/x")


@pytest.fixture()
def client(monkeypatch):
    e = Boom(bank=[BankItem(id="m", source="t", fen=MATE1, solution=["a1a8"], puzzle_rating=1500)])
    monkeypatch.setattr(app_mod, "engine", lambda: e)
    return TestClient(app_mod.app, raise_server_exceptions=False)


@pytest.fixture()
def records():
    got = []

    class H(logging.Handler):
        def emit(self, r):
            got.append(r)
    h = H()
    logging.getLogger("chessdex.access").addHandler(h)
    yield got
    logging.getLogger("chessdex.access").removeHandler(h)


def test_request_id_generated_preserved_or_replaced(client):
    r = client.get("/health")
    assert len(r.headers["x-request-id"]) == 16
    assert client.get("/health", headers={"x-request-id": "abc-12345678"}).headers["x-request-id"] == "abc-12345678"
    bad = client.get("/health", headers={"x-request-id": "<script>"}).headers["x-request-id"]
    assert bad != "<script>" and len(bad) == 16


def test_unhandled_error_is_500_without_leak_and_logged(client, records):
    sid = client.post("/sessions", json={"mode": "short"}).json()["session_id"]
    r = client.get(f"/sessions/{sid}/report", headers={"x-request-id": "istek-1234abcd"})
    assert r.status_code == 500 and r.json()["request_id"] == "istek-1234abcd"
    assert "gizli" not in r.text and "C:/x" not in r.text
    err = [x for x in records if x.levelname == "ERROR"]
    assert err and err[0].request_id == "istek-1234abcd" and err[0].route == "/sessions/{sid}/report"
    line = json.loads(observability.JsonFormatter().format(err[0]))
    assert line["request_id"] == "istek-1234abcd" and "RuntimeError" in line["exc"]
    access = [x for x in records if x.getMessage() == "istek" and x.status == 500]
    assert access and access[0].route == "/sessions/{sid}/report"           # yol şablonu: kimlik sızmaz


def test_sentry_receives_event_via_local_dsn(client, monkeypatch):
    bodies = []

    class Sink(BaseHTTPRequestHandler):
        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("content-length", 0)))
            enc = self.headers.get("content-encoding", "")
            if enc == "gzip":
                raw = gzip.decompress(raw)
            elif enc in ("deflate",):
                raw = zlib.decompress(raw)
            elif enc == "br":
                import brotli  # pragma: no cover
                raw = brotli.decompress(raw)
            bodies.append(raw.decode("utf-8", "replace"))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Sink)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    import sentry_sdk
    try:
        monkeypatch.setenv("SENTRY_DSN", f"http://publickey@127.0.0.1:{srv.server_port}/1")
        assert observability.setup_sentry("chessdex-api@test")
        sid = client.post("/sessions", json={"mode": "short"}).json()["session_id"]
        assert client.get(f"/sessions/{sid}/report", headers={"x-request-id": "sentry-req-0001"}).status_code == 500
        sentry_sdk.flush(timeout=5)
        events = "\n".join(bodies)
        assert "RuntimeError" in events and "sentry-req-0001" in events and "chessdex-api@test" in events
    finally:
        sentry_sdk.flush(timeout=2)
        monkeypatch.delenv("SENTRY_DSN", raising=False)                    # init() DSN'i ortamdan yeniden okumasın
        sentry_sdk.init(dsn="")                                            # açıkça devre dışı bırak
        srv.shutdown()


def test_sentry_disabled_without_dsn(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert observability.setup_sentry("x") is False
