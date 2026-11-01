"""Gözlemlenebilirlik: yapılandırılmış (JSON) günlükler, istek kimliği, yakalanmayan hatalar ve isteğe bağlı Sentry.

- Her istek `X-Request-ID` taşır (gelen değer güvenliyse korunur, yoksa üretilir); yanıt başlığına ve günlüğe yazılır.
- Erişim günlüğü: yöntem, yol şablonu (kimlikler sızmasın), durum, süre.
- Yakalanmayan hata: yığın izi istek kimliğiyle günlüğe; kullanıcıya iç ayrıntı vermeyen 500 + `request_id`.
- `SENTRY_DSN` tanımlıysa hatalar Sentry'ye gider (`SENTRY_TRACES_SAMPLE_RATE`, ortam `CHESSDEX_ENV`).
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import sys
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

log = logging.getLogger("chessdex.access")
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": round(record.created, 3), "level": record.levelname, "logger": record.name,
               "msg": record.getMessage()}
        for key in ("request_id", "method", "route", "status", "duration_ms"):
            if hasattr(record, key):
                out[key] = getattr(record, key)
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False)


def setup_logging() -> None:
    if os.environ.get("CHESSDEX_LOG_FORMAT", "json") != "json":
        return
    root = logging.getLogger("chessdex")
    if any(getattr(h, "_chessdex", False) for h in root.handlers):
        return
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    h._chessdex = True                                            # type: ignore[attr-defined]
    root.addHandler(h)
    root.setLevel(os.environ.get("CHESSDEX_LOG_LEVEL", "INFO"))
    root.propagate = False


def setup_sentry(release: str) -> bool:
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return False
    import sentry_sdk

    sentry_sdk.init(dsn=dsn, release=release, environment=os.environ.get("CHESSDEX_ENV", "dev"),
                    traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0")),
                    send_default_pii=False)
    return True


def _route(request: Request) -> str:
    r = request.scope.get("route")
    return getattr(r, "path", None) or "?"


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id", "")
        rid = rid if _SAFE_ID.match(rid) else secrets.token_hex(8)
        request.state.request_id = rid
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            log.exception("yakalanmayan hata", extra={"request_id": rid, "method": request.method,
                                                       "route": _route(request)})
            if os.environ.get("SENTRY_DSN"):
                import sentry_sdk  # hata burada yanıta çevrildiği için açıkça bildir

                with sentry_sdk.new_scope() as scope:
                    scope.set_tag("request_id", rid)
                    sentry_sdk.capture_exception(exc)
            response = JSONResponse({"detail": "iç hata; destek için istek kimliğini iletin", "request_id": rid},
                                    status_code=500)
        response.headers["X-Request-ID"] = rid
        log.info("istek", extra={"request_id": rid, "method": request.method, "route": _route(request),
                                 "status": response.status_code,
                                 "duration_ms": round((time.perf_counter() - t0) * 1000, 1)})
        return response
