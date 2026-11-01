"""Ölçüm servisi HTTP katmanı (CONTRACTS.md §2).

Güvenlik:
- `/games/*` uçları yalnızca oyun sunucusu içindir (saat ve hamle doğrulaması orada). `CHESSDEX_INTERNAL_TOKEN`
  tanımlıysa `X-Internal-Token` başlığı zorunludur; `CHESSDEX_ENV=production` iken belirteç tanımsızsa servis başlamaz.
  Aksi halde istemci oyun sunucusunu atlayıp hamle enjekte ederek ölçümü bozabilir.
- Girdiler katı doğrulanır (UCI, FEN, uzunluk/aralık sınırları); geçersiz girdi 422.
- Oturum oluşturma istemci başına hız sınırlıdır (429).
"""
from __future__ import annotations

import hmac
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Annotated, Literal

import chess
from fastapi import Depends, FastAPI, Header, HTTPException, Path, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, field_validator

from chessdex.measure.prior import SURVEY_EFFECTS  # anket sözlüğü tek kaynak

from . import accounts, observability
from .engine import TIME_CONTROL, Engine

log = logging.getLogger("chessdex.api")

UCI = r"^[a-h][1-8][a-h][1-8][qrbn]?$"
ID = Annotated[str, Path(min_length=4, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]


def internal_token() -> str | None:
    return os.environ.get("CHESSDEX_INTERNAL_TOKEN") or None


def check_config() -> None:
    if os.environ.get("CHESSDEX_ENV", "dev") == "production" and not internal_token():
        raise RuntimeError("CHESSDEX_ENV=production iken CHESSDEX_INTERNAL_TOKEN zorunludur")
    if not internal_token():
        log.warning("CHESSDEX_INTERNAL_TOKEN yok: /games/* uçları korumasız (yalnız geliştirme için)")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    check_config()
    yield


observability.setup_logging()
observability.setup_sentry(release="chessdex-api@0.3.0")
app = FastAPI(title="chessdex ölçüm servisi", version="0.3.0", lifespan=lifespan)
observability.install(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CHESSDEX_CORS", "http://localhost:3000").split(","),
    allow_methods=["GET", "POST"], allow_headers=["content-type"],
)


DEFAULT_DB = str(__import__("pathlib").Path(__file__).resolve().parents[2] / "data" / "sessions.sqlite3")


@lru_cache(maxsize=1)
def engine() -> Engine:
    # CHESSDEX_PG_DSN → PostgreSQL (yatay ölçek); yoksa SQLite CHESSDEX_DB
    # CHESSDEX_DB="" → kalıcılık kapalı (yalnız bellek)
    return Engine(db_path=os.environ.get("CHESSDEX_DB", DEFAULT_DB) or None,
                  pg_dsn=os.environ.get("CHESSDEX_PG_DSN") or None)


# ------------------------------------------------------------------ güvenlik yardımcıları
def require_internal(x_internal_token: Annotated[str | None, Header()] = None) -> None:
    expected = internal_token()
    if expected is None:
        return
    if not x_internal_token or not hmac.compare_digest(x_internal_token, expected):
        raise HTTPException(403, "iç uç: geçersiz ya da eksik X-Internal-Token")


class RateLimiter:
    """İstemci (IP) başına kova: `rate` istek / `per` saniye, en çok `burst` birikir."""

    def __init__(self, rate: float, per: float, burst: int):
        self.rate, self.per, self.burst = rate, per, burst
        self._b: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            tokens, last = self._b.get(key, (float(self.burst), now))
            tokens = min(self.burst, tokens + (now - last) * self.rate / self.per)
            ok = tokens >= 1.0
            self._b[key] = (tokens - 1.0 if ok else tokens, now)
            if len(self._b) > 50_000:                        # bellek koruması
                self._b.clear()
            return ok


session_limiter = RateLimiter(rate=float(os.environ.get("CHESSDEX_SESSION_RATE", 20)), per=60.0,
                              burst=int(os.environ.get("CHESSDEX_SESSION_BURST", 10)))


def trusted_proxies() -> set[str]:
    return {x.strip() for x in os.environ.get("CHESSDEX_TRUSTED_PROXIES", "").split(",") if x.strip()}


def client_ip(request: Request) -> str:
    """İstemci IP'si. Doğrudan bağlanan taraf güvenilir bir vekilse X-Forwarded-For sağdan sola yürünür ve
    güvenilir olmayan ilk adres alınır; aksi halde başlık yok sayılır (sahte başlıkla sınır atlatılamaz)."""
    peer = request.client.host if request.client else "?"
    trusted = trusted_proxies()
    if peer not in trusted:
        return peer
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    for hop in reversed(hops):
        if hop not in trusted:
            return hop
    return peer


def limit_sessions(request: Request) -> None:
    key = client_ip(request)
    if not session_limiter.allow(key):
        raise HTTPException(429, "çok fazla oturum isteği; biraz sonra tekrar deneyin")


def _msg(e: Exception) -> str:
    return str(e.args[0]) if e.args else str(e)          # KeyError'ın str()'i mesajı tırnaklar


def _session(sid: str):
    try:
        return engine().get(sid)
    except KeyError as e:
        raise HTTPException(404, _msg(e)) from None


def _guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except KeyError as e:
        raise HTTPException(404, _msg(e)) from None
    except ValueError as e:
        raise HTTPException(409, _msg(e)) from None


def _valid_fen(v: str) -> str:
    try:
        chess.Board(v)
    except ValueError:
        raise ValueError("geçersiz FEN") from None
    return v


# ------------------------------------------------------------------ gövdeler
class CreateBody(BaseModel):
    mode: Literal["full", "short"] = "full"
    survey: dict[str, str] | None = None
    turnstile_token: str | None = Field(None, max_length=2048)

    @field_validator("survey")
    @classmethod
    def _survey(cls, v):
        if v is None:
            return v
        for key, val in v.items():
            if key not in SURVEY_EFFECTS:
                raise ValueError(f"bilinmeyen anket alanı: {key}")
            if val not in SURVEY_EFFECTS[key]:
                raise ValueError(f"geçersiz anket değeri: {key}={val}")
        return v


class ResponseBody(BaseModel):
    token: str = Field(min_length=1, max_length=64)
    moves: list[Annotated[str, Field(pattern=UCI)]] = Field(max_length=20)
    elapsed_ms: int = Field(0, ge=0, le=3_600_000)
    partial: bool = False


class BotMoveBody(BaseModel):
    fen: str = Field(max_length=100)
    ply: int = Field(ge=0, le=2000)

    @field_validator("fen")
    @classmethod
    def _fen(cls, v: str) -> str:
        return _valid_fen(v)


class UserMoveBody(BaseModel):
    ply: int = Field(ge=0, le=2000)
    fen_before: str = Field(max_length=100)
    uci: str = Field(pattern=UCI)
    spent_ms: int = Field(ge=0, le=3_600_000)
    clock_ms: int = Field(ge=0, le=36_000_000)
    focus_lost: bool = False      # istemcinin bildirdiği sekme/odak kaybı (bütünlük sinyali; sahte olabilir)

    @field_validator("fen_before")
    @classmethod
    def _fen(cls, v: str) -> str:
        return _valid_fen(v)


class FinishBody(BaseModel):
    result: Literal["1-0", "0-1", "1/2-1/2"]
    reason: str = Field(max_length=32)
    pgn: str | None = Field(None, max_length=20_000)


# ------------------------------------------------------------------ uçlar
@app.get("/health")
def health():
    e = engine()
    return {"ok": True, "human_model": f"{e.model.name}-{e.model.version}",
            "stockfish": e.analyzer.available, "bank_items": len(e.pool),
            "bank_source": e.bank_source, "internal_auth": internal_token() is not None,
            "turnstile": accounts.turnstile_secret() is not None,
            "sessions": len(e.sessions),
            "store": {"SessionStore": "sqlite", "PgSessionStore": "postgres"}.get(type(e.store).__name__, "memory")}


@app.post("/sessions", dependencies=[Depends(limit_sessions)])
def create(body: CreateBody, request: Request):
    if not accounts.turnstile_ok(body.turnstile_token, client_ip(request)):
        raise HTTPException(403, "bot doğrulaması başarısız; sayfayı yenileyip tekrar deneyin")
    e = engine()
    s = e.create(body.mode, body.survey)
    return {"session_id": s.id, "estimate": e.estimate(s)}


@app.get("/sessions/{sid}/next-item")
def next_item(sid: ID):
    return engine().next_item(_session(sid))


@app.post("/sessions/{sid}/responses")
def respond(sid: ID, body: ResponseBody):
    return _guard(engine().respond, _session(sid), body.token, body.moves, body.elapsed_ms, body.partial)


@app.post("/sessions/{sid}/game")
def start_game(sid: ID):
    g = _guard(engine().start_game, _session(sid))
    return {"game_id": g.id, "bot_level": g.bot_level, "user_color": g.user_color,
            "time_control": TIME_CONTROL, "seed": g.seed}


@app.post("/games/{gid}/bot-move", dependencies=[Depends(require_internal)])
def bot_move(gid: ID, body: BotMoveBody):
    return _guard(engine().bot_move, gid, body.fen, body.ply)


@app.post("/games/{gid}/user-move", dependencies=[Depends(require_internal)])
def user_move(gid: ID, body: UserMoveBody):
    _guard(engine().user_move, gid, body.ply, body.fen_before, body.uci, body.spent_ms, body.clock_ms,
           body.focus_lost)
    return {"ok": True}


@app.post("/games/{gid}/finish", dependencies=[Depends(require_internal)])
def finish(gid: ID, body: FinishBody):
    _guard(engine().finish, gid, body.result, body.reason, body.pgn)
    return {"ok": True}


@app.get("/sessions/{sid}/report")
def report(sid: ID):
    return _guard(engine().report, _session(sid))


# ------------------------------------------------------------------ harici hesap bağlama (pilot)
@app.post("/sessions/{sid}/link/lichess")
def link_lichess(sid: ID):
    """Lichess OAuth (PKCE) başlatır; istemci dönen adrese yönlendirir. İsteğe bağlı, açık rıza ile."""
    return {"authorize_url": engine().link_start(_session(sid))}


@app.get("/oauth/lichess/callback")
def lichess_callback(state: Annotated[str, Query(max_length=128)] = "",
                     code: Annotated[str | None, Query(max_length=512)] = None,
                     error: Annotated[str | None, Query(max_length=128)] = None):
    """Lichess'ten dönüş: hesabı doğrular ve kullanıcıyı web raporuna geri gönderir (belirteç saklanmaz)."""
    sid = next((x.id for x in engine().sessions.values()
                if getattr(x, "oauth", None) and hmac.compare_digest(x.oauth["state"], state)), None) if state else None
    if sid is None:
        return RedirectResponse(f"{accounts.web_url()}/?link=expired", status_code=303)
    back = f"{accounts.web_url()}/report/{sid}"
    if error or not code:
        engine().sessions[sid].oauth = None
        return RedirectResponse(f"{back}?link=denied", status_code=303)
    try:
        engine().link_callback(code, state)
    except (KeyError, ValueError):
        return RedirectResponse(f"{back}?link=failed", status_code=303)
    return RedirectResponse(f"{back}?link=ok", status_code=303)


class ChesscomBody(BaseModel):
    username: str = Field(pattern=accounts.USERNAME_RE)


@app.post("/sessions/{sid}/link/chesscom")
def link_chesscom(sid: ID, body: ChesscomBody):
    """Chess.com sahiplik doğrulaması: kullanıcıya profilinin Konum alanına yazacağı geçici bir kod verir."""
    code = engine().chesscom_start(_session(sid), body.username)
    return {"code": code, "expires_in_s": accounts.CODE_TTL_S,
            "instructions": "Chess.com > Ayarlar > Profil > Konum alanına kodu yazıp kaydedin, sonra Doğrula'ya basın."}


@app.post("/sessions/{sid}/link/chesscom/verify")
def verify_chesscom(sid: ID):
    return {"external": _guard(engine().chesscom_verify, _session(sid))}
