"""Oturum motoru: senaryolar → maç → birleştirme → rapor. HTTP'den bağımsız, test edilebilir."""
from __future__ import annotations

import hashlib
import os
import secrets
import threading
import time
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import chess
import numpy as np

from chessdex.bank.loader import demo_items, load_items
from chessdex.bank.models import BankItem
from chessdex.bank.scoring import check_line, opponent_reply, score_attempt
from chessdex.bank.transforms import transform_item, valid_transforms
from chessdex.engines.exclusion import exclusion_reason
from chessdex.engines.human import EXTRAP_HIGH, EXTRAP_LOW, MAX_EXT, get_model, sample_move, think_time_ms
from chessdex.engines.integrity import integrity_score
from chessdex.engines.stockfish import Analyzer
from chessdex.measure import calibration
from chessdex.measure import match as M
from chessdex.measure.grid import GRID
from chessdex.measure.irt import FAST_OFFSET, POSITIONAL_OFFSETS, Item, log_lik_graded
from chessdex.measure.loss_model import LossModel
from chessdex.measure.posterior import Posterior
from chessdex.measure.prior import DEFAULT_MEAN, DEFAULT_SD, survey_prior
from chessdex.measure.scales import convert
from chessdex.measure.selection import ItemPool, select_next
from chessdex.measure.stopping import MAX_ITEMS, SHORT_BUDGET_MS, should_stop

from . import accounts
from .store import open_store

MODEL_VERSION = {"measure": "0.3.0", "lambda_maia": M.DEFAULT_LAMBDA, "lambda_loss": M.LOSS_LAMBDA,
                 "exclusion": "backtest-2026-10-29",
                 "maia_extrap": f"low={EXTRAP_LOW},high={EXTRAP_HIGH},max={MAX_EXT}",
                 "b_mapping": "alpha=-200,beta=1", "prior": f"N({DEFAULT_MEAN:.0f},{DEFAULT_SD:.0f})",
                 "scales": "pilot-öncesi-yaklaşık"}
# Kayıp modeli bu düğüm sayısındaki analizle öğrenildi; maç analizi aynı derinlikte yapılmalı (aksi halde
# ölçülen kayıplar sistematik kayar). Belirlenimcilik korunur: sabit düğüm, tek iş parçacığı.
MATCH_ANALYSIS_NODES_DEFAULT = 100_000
DEFAULT_BANK = Path(__file__).resolve().parents[2] / "data" / "bank.jsonl"   # Lichess'ten üretilen banka
SUBSKILL_MAX_WIDTH = 400
CRITICAL_MIN_WP_LOSS = 0.05      # kritik an: kazanma şansında en az %5 kayıp (Stockfish)
CRITICAL_MIN_LOG_RATIO = 1.0     # motorsuz: oynanan hamle tipik hamleden ≥ e kat az olası
# Bellek koruması: etkinliği bu kadar süredir olmayan oturumlar silinir; toplam sayı üst sınırı aşarsa en eskiler gider.
SESSION_TTL_S = float(os.environ.get("CHESSDEX_SESSION_TTL_S", 6 * 3600))
MAX_SESSIONS = int(os.environ.get("CHESSDEX_MAX_SESSIONS", 20_000))
TIME_CONTROL = {"initial_ms": 600_000, "increment_ms": 5_000}
PROMPTS = {
    "tactics": "Taktik: en iyi devamı bulun.",
    "endgame": "Oyun sonu: en iyi hamleyi bulun.",
    "defense": "Savunma: tehdidi karşılayan en iyi hamleyi bulun.",
    "positional": "Pozisyonel: en iyi planı seçin.",
}


def to_irt(it: BankItem, cal: dict | None = None) -> Item:
    """BankItem → IRT senaryosu; `cal` verilirse pilot kalibrasyonu (tür başına α, β, γ) uygulanır."""
    if it.offsets:
        offsets = tuple(float(x) for x in it.offsets)
    else:
        offsets = POSITIONAL_OFFSETS if it.move_scores else (0.0, FAST_OFFSET)
    item = Item(it.id, b=float(it.b), a=float(it.a), c=float(it.c), kind=it.kind, offsets=offsets)
    return calibration.apply(item, cal)


def _seed(*parts) -> int:
    return int.from_bytes(hashlib.sha256("|".join(map(str, parts)).encode()).digest()[:8], "big")


@dataclass
class Pending:
    token: str
    item: BankItem          # dönüştürülmüş
    irt: Item
    transform: str
    shown_at: float


@dataclass
class Game:
    id: str
    bot_level: int
    user_color: str
    seed: int
    moves: list[dict] = field(default_factory=list)
    futures: list[Future] = field(default_factory=list)
    result: str | None = None
    reason: str | None = None
    pgn: str | None = None

    def __getstate__(self):                      # analiz geleceği (Future) kalıcı depoya yazılamaz
        d = dict(self.__dict__)
        d["futures"] = []
        return d


@dataclass
class Session:
    id: str
    mode: str
    log_prior: np.ndarray
    post: Posterior
    used: set = field(default_factory=set)
    kinds: Counter = field(default_factory=Counter)
    responses: list[dict] = field(default_factory=list)
    item_ll: dict = field(default_factory=dict)       # tür → toplam log olabilirlik
    pending: Pending | None = None
    stage: str = "items"                              # items | game | done
    game: Game | None = None
    final: Posterior | None = None
    match_used: bool = False
    flags: list[str] = field(default_factory=list)
    started: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    oauth: dict | None = None                         # bekleyen hesap bağlama (state, PKCE doğrulayıcı)
    external: dict | None = None                      # doğrulanmış harici hesap (pilot kalibrasyonu)


class Engine:
    def __init__(self, bank: list[BankItem] | None = None, workers: int = 2, db_path: str | None = None,
                 pg_dsn: str | None = None):
        self.bank_source = "custom"
        bank_from_disk = bank is None
        if bank is None:
            path = os.environ.get("CHESSDEX_BANK") or (str(DEFAULT_BANK) if DEFAULT_BANK.exists() else None)
            bank = load_items(path) if path else demo_items()
            self.bank_source = path or "demo"
        self.bank = {it.id: it for it in bank}
        cal_path = os.environ.get("CHESSDEX_ITEM_CALIBRATION")
        self.calibration = calibration.load(cal_path) if (cal_path or bank_from_disk) else None
        self.pool = ItemPool([to_irt(it, self.calibration) for it in bank])
        self.sessions: dict[str, Session] = {}
        self.games: dict[str, Session] = {}
        self.model = get_model()
        self.loss_model = LossModel.load()
        nodes = int((self.loss_model.meta.get("bt_nodes") if self.loss_model else None)
                    or MATCH_ANALYSIS_NODES_DEFAULT)
        self.analyzer = Analyzer(nodes=nodes)
        self.pool_exec = ThreadPoolExecutor(max_workers=workers)
        self.lock = threading.RLock()
        self.store = open_store(db_path, pg_dsn)
        if self.store is not None:
            self._restore()

    def _restore(self) -> None:
        """Kalıcı depodan süresi dolmamış oturumları yükler; analizi yarım kalmış hamleleri yeniden kuyruğa alır."""
        for s in self.store.load_all(SESSION_TTL_S):
            self.sessions[s.id] = s
            if s.game is not None:
                self.games[s.game.id] = s
                for rec in s.game.moves:
                    if "weight" not in rec:
                        s.game.futures.append(self.pool_exec.submit(self._analyse_move, s, rec))

    def _persist(self, s: Session) -> None:
        if self.store is not None:
            with self.lock:
                self.store.save(s)

    # ---- oturum ----
    def create(self, mode: str = "full", survey: dict | None = None) -> Session:
        self.cleanup()
        sid = secrets.token_urlsafe(12)
        lp = survey_prior(survey)
        s = Session(sid, mode, lp, Posterior(lp))
        with self.lock:
            self.sessions[sid] = s
        self._persist(s)
        return s

    def get(self, sid: str) -> Session:
        s = self.sessions.get(sid)
        if s is None:
            raise KeyError("oturum bulunamadı")
        s.last_active = time.time()
        return s

    def cleanup(self, now: float | None = None) -> int:
        """Süresi dolan oturumları (ve oyun eşlemelerini) siler; kapasite aşılırsa en az yeni etkinlikli olanları da."""
        now = time.time() if now is None else now
        with self.lock:
            drop = {sid for sid, s in self.sessions.items() if now - s.last_active > SESSION_TTL_S}
            overflow = len(self.sessions) - len(drop) - MAX_SESSIONS + 1
            if overflow > 0:
                alive = sorted((s.last_active, sid) for sid, s in self.sessions.items() if sid not in drop)
                drop |= {sid for _, sid in alive[:overflow]}
            for sid in drop:
                s = self.sessions.pop(sid)
                if s.game is not None:
                    self.games.pop(s.game.id, None)
        if self.store is not None:
            self.store.delete(drop)
        return len(drop)

    def estimate(self, s: Session) -> dict:
        post = s.final or s.post
        return {**post.summary(), "n_items": len(s.responses), "stage": s.stage}

    def items_done(self, s: Session) -> bool:
        spent = sum(r["elapsed_ms"] for r in s.responses)
        return should_stop(s.post, len(s.responses), s.mode, spent) or len(s.used) >= len(self.pool)

    def next_item(self, s: Session) -> dict:
        if s.stage != "items" or self.items_done(s):
            return {"done": True}
        if s.pending is None:
            rng = np.random.default_rng(_seed(s.id, len(s.responses)))
            it = select_next(s.post, self.pool, s.used, rng, s.kinds)
            if it is None:
                return {"done": True}
            raw = self.bank[it.id]
            options = valid_transforms(raw.fen)
            name = options[int(rng.integers(len(options)))]
            shown = transform_item(raw, name)
            s.pending = Pending(secrets.token_urlsafe(9), shown, it, name, time.time())
            self._persist(s)
        p = s.pending
        board = chess.Board(p.item.fen)
        out = {"token": p.token, "fen": p.item.fen,
               "orientation": "white" if board.turn == chess.WHITE else "black",
               "kind": p.item.kind, "prompt": PROMPTS[p.item.kind], "n_moves": len(p.item.solution),
               "index": len(s.responses) + 1, "max_items": MAX_ITEMS,
               # sayfa yenilenirse istemci sayacı sıfırlanmasın: sunucunun ölçtüğü süre (puanlama da bunu kullanır)
               "elapsed_ms": int((time.time() - p.shown_at) * 1000)}
        if p.item.choices:
            out["choices"] = list(p.item.choices)
        if s.mode == "short":   # kısa mod zaman bütçesiyle de biter: ilerleme çubuğu için
            out["time_budget_ms"] = int(SHORT_BUDGET_MS)
            out["spent_ms"] = sum(r["elapsed_ms"] for r in s.responses)
        return {"done": False, "item": out}

    def respond(self, s: Session, token: str, moves: list[str], elapsed_ms: int, partial: bool = False) -> dict:
        p = s.pending
        if p is None or p.token != token:
            raise ValueError("geçersiz ya da süresi geçmiş senaryo")
        # `moves` tam çizgidir: oyuncu hamleleri çift, sunucunun verdiği rakip cevapları tek indekslerde
        player = list(moves[0::2])
        if partial and not p.item.move_scores:
            ok, done = check_line(p.item, player)
            if ok and not done:
                return {"continue": True, "reply": opponent_reply(p.item, player)}
        server_ms = int((time.time() - p.shown_at) * 1000)
        # süre sunucuda ölçülür; istemci değeri yalnızca ağ gecikmesini düşmek için alt sınır olarak kullanılır
        used_ms = max(min(server_ms, int(elapsed_ms)), int(server_ms * 0.8)) if elapsed_ms else server_ms
        k, correct = score_attempt(p.item, moves, used_ms, include_opponent=True)
        ll = log_lik_graded(p.irt, min(k, p.irt.n_cat - 1))
        s.post.update(ll)
        s.item_ll[p.item.kind] = s.item_ll.get(p.item.kind, 0) + ll
        s.used.add(p.irt.id)
        s.kinds[p.item.kind] += 1
        s.responses.append({"item_id": p.irt.id, "transform": p.transform, "moves": moves,
                            "elapsed_ms": used_ms, "client_ms": elapsed_ms, "score": k, "correct": correct,
                            "kind": p.item.kind})
        s.pending = None
        done = self.items_done(s)
        if done and s.mode == "short":
            self._finalize(s)
        self._persist(s)
        return {"correct": correct, "score": k, "solution": p.item.solution,
                "estimate": self.estimate(s), "done": done}

    # ---- maç ----
    def start_game(self, s: Session) -> Game:
        if s.game is not None:
            return s.game
        if s.mode != "full":
            raise ValueError("kısa modda maç yok")
        s.stage = "game"
        seed = _seed(s.id, "game")
        level = int(np.clip(round(s.post.median() / 10) * 10, 400, 3000))
        g = Game(secrets.token_urlsafe(9), level, "white" if seed % 2 == 0 else "black", seed)
        s.game = g
        self.games[g.id] = s
        self._persist(s)
        return g

    def game_session(self, gid: str) -> Session:
        s = self.games.get(gid)
        if s is None:
            raise KeyError("oyun bulunamadı")
        s.last_active = time.time()
        return s

    def bot_move(self, gid: str, fen: str, ply: int) -> dict:
        s = self.game_session(gid)
        g = s.game
        rng = np.random.default_rng(_seed(g.seed, ply))
        uci = sample_move(self.model, fen, g.bot_level, g.bot_level, rng)
        ent = self.model.entropy(fen, g.bot_level)
        return {"uci": uci, "think_ms": think_time_ms(fen, ent, rng)}

    def user_move(self, gid: str, ply: int, fen_before: str, uci: str, spent_ms: int, clock_ms: int,
                  focus_lost: bool = False) -> None:
        s = self.game_session(gid)
        rec = {"ply": ply, "fen": fen_before, "uci": uci, "spent_ms": spent_ms, "clock_ms": clock_ms,
               "focus_lost": bool(focus_lost)}
        with self.lock:
            if s.game.result is not None:
                raise ValueError("oyun bitti")
            # oyun sunucusu başarısız sandığı isteği yeniden dener: aynı ply ikinci kez sayılmasın (idempotent)
            if any(m["ply"] == ply for m in s.game.moves):
                return
            s.game.moves.append(rec)
            s.game.futures.append(self.pool_exec.submit(self._analyse_move, s, rec))
        self._persist(s)

    def _analyse_move(self, s: Session, rec: dict) -> None:
        g = s.game
        fen, uci = rec["fen"], rec["uci"]
        try:
            grid = self.model.move_prob_grid(fen, uci, g.bot_level)
        except ValueError:
            with self.lock:
                rec.update(weight=0.0, reason="illegal")
            self._persist(s)
            return
        sf = self.analyzer.analyse(fen) if self.analyzer.available else None
        eval_cp = sf["cp"] if sf and sf["cp"] is not None else (10_000 if sf and sf["mate"] else None)
        reason, weight = exclusion_reason(rec["ply"], fen, uci, grid, eval_cp, rec["clock_ms"])
        loss = None
        if sf:   # hamle öncesi analiz zaten var; yalnızca hamle sonrasını analiz et (2 yerine 1 ek çağrı)
            board = chess.Board(fen)
            board.push_uci(uci)
            after = self.analyzer.analyse(board.fen())
            if after is not None:
                loss = max(0.0, sf["win_prob"] - (1.0 - after["win_prob"]))
        loss_ll = None
        if loss is not None and self.loss_model is not None:
            loss_ll = self.loss_model.move_log_lik(loss, eval_cp or 0.0)
        entropy = float(self.model.entropy(fen, g.bot_level))
        with self.lock:
            rec.update(grid=grid, weight=weight, reason=reason, eval_cp=eval_cp, win_prob_loss=loss, loss_ll=loss_ll,
                       engine_best=sf["best"] if sf else None, entropy=entropy)
        self._persist(s)

    def finish(self, gid: str, result: str, reason: str, pgn: str | None) -> None:
        s = self.game_session(gid)
        g = s.game
        if s.stage == "done":                    # yeniden denenen finish: idempotent
            return
        g.result, g.reason, g.pgn = result, reason, pgn
        for f in list(g.futures):
            f.result()
        self._finalize(s)
        self._persist(s)

    def _finalize(self, s: Session) -> None:
        final = s.post.copy()
        g = s.game
        if g is not None and g.result:
            ev = [M.MoveEvidence(m["ply"], m["grid"], m["weight"], m["reason"], m.get("loss_ll"))
                  for m in g.moves if "grid" in m]
            score = {"1-0": 1.0, "0-1": 0.0}.get(g.result, 0.5)
            if g.user_color == "black" and g.result != "1/2-1/2":
                score = 1.0 - score
            ll, used = M.match_log_lik(ev, score=score, bot_level=g.bot_level)
            s.match_used = used
            if used:
                final.update(ll)
            else:
                s.flags.append("short_game")
            integ = self._integrity(s, final.median())
            if integ["flag"]:
                s.flags.append("low_reliability")
        s.final = final
        s.stage = "done"

    def _integrity(self, s: Session, theta: float) -> dict:
        i = int(np.argmin(np.abs(GRID - theta)))
        rows = [{"engine_match": (m["engine_best"] == m["uci"]) if m.get("engine_best") else None,
                 "human_prob": float(m["grid"][i]), "spent_ms": m["spent_ms"],
                 "complexity": m.get("entropy"), "focus_lost": bool(m.get("focus_lost"))}
                for m in s.game.moves if "grid" in m]
        return integrity_score(rows)

    # ---- harici hesap bağlama (pilot) ----
    def link_start(self, s: Session) -> str:
        verifier, challenge = accounts.pkce_pair()
        state = secrets.token_urlsafe(24)
        s.oauth = {"platform": "lichess", "state": state, "verifier": verifier, "created": time.time()}
        self._persist(s)
        return accounts.authorize_url(state, challenge)

    def link_callback(self, code: str, state: str, fetch=None) -> Session:
        with self.lock:
            s = next((x for x in self.sessions.values()
                      if getattr(x, "oauth", None) and secrets.compare_digest(x.oauth["state"], state)), None)
        if s is None:
            raise KeyError("bağlantı isteği bulunamadı ya da süresi doldu")
        pending = s.oauth
        s.oauth = None
        if time.time() - pending["created"] > accounts.STATE_TTL_S:
            self._persist(s)
            raise ValueError("bağlantı isteğinin süresi doldu")
        try:
            s.external = accounts.exchange_and_fetch(code, pending["verifier"], fetch)
        finally:
            self._persist(s)
        return s

    def chesscom_start(self, s: Session, username: str) -> str:
        code = accounts.chesscom_code()
        s.oauth = {"platform": "chesscom", "username": username, "code": code, "created": time.time()}
        self._persist(s)
        return code

    def chesscom_verify(self, s: Session, fetch=None) -> dict:
        pending = getattr(s, "oauth", None)
        if not pending or pending.get("platform") != "chesscom":
            raise ValueError("önce Chess.com kullanıcı adı girilmeli")
        if time.time() - pending["created"] > accounts.CODE_TTL_S:
            s.oauth = None
            self._persist(s)
            raise ValueError("doğrulama kodunun süresi doldu; yeni kod alın")
        s.external = accounts.chesscom_verify(pending["username"], pending["code"], fetch)
        s.oauth = None
        self._persist(s)
        return s.external

    def _comparison(self, s: Session, est: dict) -> dict | None:
        ext = getattr(s, "external", None)
        if not ext or ext.get("rating") is None:
            return None
        r = ext["rating"]
        # Chess.com rating'i farklı skalada: tahminin Chess.com karşılığıyla karşılaştır
        ref = convert(est)["chesscom"] if ext.get("platform") == "chesscom" else est
        return {"verified_rating": r, "difference": ref["median"] - r, "inside_90": ref["lo90"] <= r <= ref["hi90"],
                "scale": ext.get("platform", "lichess")}

    # ---- rapor ----
    def report(self, s: Session) -> dict:
        if s.stage != "done":
            if s.mode == "short" and self.items_done(s):
                self._finalize(s)
                self._persist(s)
            else:
                raise ValueError("oturum henüz bitmedi")
        est = self.estimate(s)
        subs = {}
        for kind in ("tactics", "endgame", "positional", "defense"):
            ll = s.item_ll.get(kind)
            if ll is None:
                subs[kind] = None
                continue
            sm = Posterior(s.log_prior).update(ll).summary()
            subs[kind] = sm if sm["hi90"] - sm["lo90"] <= SUBSKILL_MAX_WIDTH else None
        subs["time"] = None   # zaman yönetimi alt skoru: pilot verisi gerekiyor
        return {
            "estimate": est,
            "scales": convert(est),
            "posterior": {"grid": GRID[::5].tolist(), "p": s.final.p[::5].tolist()},
            "subskills": subs,
            "critical_moments": self._critical(s),
            "flags": s.flags,
            "match_used": s.match_used,
            "external": getattr(s, "external", None),
            "comparison": self._comparison(s, est),
            "model_version": {**MODEL_VERSION, "human_model": f"{self.model.name}-{self.model.version}",
                              "stockfish": f"nodes={self.analyzer.nodes}" if self.analyzer.available else "absent",
                              "item_calibration": (self.calibration or {}).get("version", "none"),
                              "loss_model": (self.loss_model.meta.get("source") if self.loss_model else "absent")},
        }

    def _critical(self, s: Session) -> list[dict]:
        g = s.game
        if g is None:
            return []
        theta = s.final.median()
        i = int(np.argmin(np.abs(GRID - theta)))
        rows = []
        for m in g.moves:
            if "grid" not in m or m["weight"] <= 0:
                continue
            probs = self.model.move_probs(m["fen"], int(GRID[i]), g.bot_level)
            typical = max(probs, key=probs.get)
            if m.get("win_prob_loss") is not None:
                loss, src = float(m["win_prob_loss"]), "stockfish"
            else:   # motor yoksa: θ̂ seviyesindeki tipik hamleye göre olasılık oranı
                loss, src = float(np.log(probs[typical] / max(probs.get(m["uci"], 1e-6), 1e-6))), "human_model"
            # yalnızca anlamlı kayıplar: Stockfish'te ≥ %5 kazanma şansı, motorsuzda tipik hamleden ≥ e kat az olası
            if typical != m["uci"] and loss >= (CRITICAL_MIN_WP_LOSS if src == "stockfish" else CRITICAL_MIN_LOG_RATIO):
                board = chess.Board(m["fen"])
                rows.append({"ply": m["ply"] + 1, "move_no": board.fullmove_number,
                             "side": "white" if board.turn == chess.WHITE else "black",
                             "played": m["uci"], "played_san": board.san(chess.Move.from_uci(m["uci"])),
                             "typical": typical, "typical_san": board.san(chess.Move.from_uci(typical)),
                             "eval_loss": round(loss, 3), "source": src, "fen": m["fen"]})
        return sorted(rows, key=lambda r: -r["eval_loss"])[:3]
