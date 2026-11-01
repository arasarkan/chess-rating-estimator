"""Harici hesap bağlama (pilot kalibrasyonunun "gerçek değeri"; plan: external_accounts, rating_snapshots).

Lichess OAuth2 PKCE: Lichess açık istemcileri kayıtsız kabul eder, gizli anahtar gerekmez. Akış:
  1. `start` → PKCE doğrulayıcı + `state` oturuma yazılır; kullanıcı Lichess yetkilendirme sayfasına gider (kapsam yok:
     yalnız herkese açık profil).
  2. `callback` → kod, doğrulayıcıyla erişim belirtecine çevrilir; `/api/account`'tan rapid rating/RD/oyun
     sayısı alınır; belirteç SAKLANMAZ ve hemen iptal edilir.
Kalibrasyon uygunluğu (plan "Hile önleme ve veri kalitesi"): RD < 75, ≥ 30 rated rapid oyun, geçici değil.
HTTP çağrıları enjekte edilebilir (`fetch`) — testler ağ kullanmaz.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse
import urllib.request
from typing import Callable

LICHESS = os.environ.get("CHESSDEX_LICHESS_URL", "https://lichess.org")
MAX_RD = 75
MIN_GAMES = 30
STATE_TTL_S = 15 * 60

Fetch = Callable[[str, str, dict | None, dict | None], tuple[int, dict]]


def default_fetch(method: str, url: str, form: dict | None = None, headers: dict | None = None) -> tuple[int, dict]:
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    hdrs = {"Accept": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read()
            return r.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


def client_id() -> str:
    return os.environ.get("CHESSDEX_LICHESS_CLIENT_ID", "chessdex")


def redirect_uri() -> str:
    return os.environ.get("CHESSDEX_PUBLIC_API_URL", "http://localhost:8000").rstrip("/") + "/oauth/lichess/callback"


def web_url() -> str:
    return os.environ.get("CHESSDEX_WEB_URL", "http://localhost:3000").rstrip("/")


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]                       # 43–128 karakter (RFC 7636)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorize_url(state: str, challenge: str) -> str:
    q = {"response_type": "code", "client_id": client_id(), "redirect_uri": redirect_uri(),
         "code_challenge_method": "S256", "code_challenge": challenge, "state": state}
    return f"{LICHESS}/oauth?{urllib.parse.urlencode(q)}"


def eligibility(rapid: dict) -> tuple[bool, list[str]]:
    reasons = []
    if rapid.get("prov"):
        reasons.append("geçici rating")
    if (rapid.get("rd") or 999) >= MAX_RD:
        reasons.append(f"RD ≥ {MAX_RD}")
    if (rapid.get("games") or 0) < MIN_GAMES:
        reasons.append(f"{MIN_GAMES}'dan az rapid oyun")
    return not reasons, reasons


def account_record(account: dict) -> dict:
    rapid = (account.get("perfs") or {}).get("rapid") or {}
    ok, reasons = eligibility(rapid)
    return {"platform": "lichess", "username": account.get("username") or account.get("id"),
            "rating": rapid.get("rating"), "rd": rapid.get("rd"), "games": rapid.get("games"),
            "provisional": bool(rapid.get("prov")), "verified_by": "oauth", "verified_at": time.time(),
            "calibration_eligible": ok, "ineligible_reasons": reasons}


def exchange_and_fetch(code: str, verifier: str, fetch: Fetch | None = None) -> dict:
    fetch = fetch or default_fetch
    status, tok = fetch("POST", f"{LICHESS}/api/token", {
        "grant_type": "authorization_code", "code": code, "code_verifier": verifier,
        "redirect_uri": redirect_uri(), "client_id": client_id()}, None)
    token = tok.get("access_token") if status == 200 else None
    if not token:
        why = tok.get("error_description") or tok.get("error") or status
        raise ValueError(f"Lichess yetkilendirmesi başarısız: {why}")
    auth = {"Authorization": f"Bearer {token}"}
    try:
        status, acct = fetch("GET", f"{LICHESS}/api/account", None, auth)
        if status != 200:
            raise ValueError(f"Lichess hesabı okunamadı (HTTP {status})")
        return account_record(acct)
    finally:
        fetch("DELETE", f"{LICHESS}/api/token", None, auth)          # belirteci saklamıyoruz: iptal et


# ------------------------------------------------------------------ Chess.com (profil koduyla doğrulama)
# Chess.com'un herkese açık API'si anahtar gerektirmez. Sahiplik, kullanıcının profilinin "Konum" (ya da "Ad") alanına
# geçici bir kod yazmasıyla kanıtlanır; kod okunduktan sonra kullanıcı alanı eski haline getirebilir.
CHESSCOM_API = os.environ.get("CHESSDEX_CHESSCOM_API", "https://api.chess.com/pub")
CHESSCOM_UA = {"User-Agent": "chessdex/0.3 (satranc gucu tahmini; pilot dogrulama)"}
CODE_TTL_S = 30 * 60
USERNAME_RE = r"^[A-Za-z0-9_-]{3,25}$"


def chesscom_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"                      # karışan karakterler yok
    return "chessdex-" + "".join(secrets.choice(alphabet) for _ in range(6))


def chesscom_verify(username: str, code: str, fetch: Fetch | None = None) -> dict:
    fetch = fetch or default_fetch
    user = urllib.parse.quote(username.lower())
    status, prof = fetch("GET", f"{CHESSCOM_API}/player/{user}", None, CHESSCOM_UA)
    if status == 404:
        raise ValueError("Chess.com kullanıcısı bulunamadı")
    if status != 200:
        raise ValueError(f"Chess.com profili okunamadı (HTTP {status})")
    fields = " ".join(str(prof.get(k) or "") for k in ("location", "name"))
    if code.lower() not in fields.lower():
        raise ValueError("Kod profilin Konum ya da Ad alanında bulunamadı (kaydettikten sonra birkaç dakika sürebilir)")
    status, stats = fetch("GET", f"{CHESSCOM_API}/player/{user}/stats", None, CHESSCOM_UA)
    rapid = (stats or {}).get("chess_rapid") or {} if status == 200 else {}
    last, rec = rapid.get("last") or {}, rapid.get("record") or {}
    games = sum(int(rec.get(k) or 0) for k in ("win", "loss", "draw"))
    norm = {"rating": last.get("rating"), "rd": last.get("rd"), "games": games, "prov": False}
    ok, reasons = eligibility(norm)
    if last.get("rating") is None:
        ok, reasons = False, ["rapid rating yok"]
    return {"platform": "chesscom", "username": prof.get("username") or username, "rating": last.get("rating"),
            "rd": last.get("rd"), "games": games, "provisional": False, "verified_by": "profile_code",
            "verified_at": time.time(), "calibration_eligible": ok, "ineligible_reasons": reasons}


# ------------------------------------------------------------------ Cloudflare Turnstile (bot koruması)
# CHESSDEX_TURNSTILE_SECRET tanımlıysa oturum oluşturma geçerli bir Turnstile belirteci ister. Cloudflare'in resmî test
# anahtarları: gizli 1x0000000000000000000000000000000AA (her zaman geçer),
# 2x0000000000000000000000000000000AA (her zaman reddeder).
TURNSTILE_VERIFY = os.environ.get("CHESSDEX_TURNSTILE_VERIFY_URL",
                                  "https://challenges.cloudflare.com/turnstile/v0/siteverify")


def turnstile_secret() -> str | None:
    return os.environ.get("CHESSDEX_TURNSTILE_SECRET") or None


def turnstile_ok(token: str | None, remote_ip: str | None, fetch: Fetch | None = None) -> bool:
    secret = turnstile_secret()
    if secret is None:
        return True                                                    # yapılandırılmamış: kapalı
    if not token:
        return False
    form = {"secret": secret, "response": token}
    if remote_ip:
        form["remoteip"] = remote_ip
    try:
        status, body = (fetch or default_fetch)("POST", TURNSTILE_VERIFY, form, None)
    except OSError:
        return False                                                   # doğrulanamadıysa kabul etme
    return status == 200 and bool(body.get("success"))
