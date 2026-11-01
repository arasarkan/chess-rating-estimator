"""İnsan hamle modeli: P(hamle | pozisyon, θ).

İki uygulama vardır:
- `Maia2Model`: `maia2` paketi kuruluysa gerçek Maia-2 modeli.
- `HeuristicHumanModel`: Maia yokken kullanılan belirlenimci yedek. Malzeme + basit
  PST ile 2 yarım hamlelik arama yapar, skorları θ'ya bağlı sıcaklıkta softmax'a
  sokar ve θ ile azalan bir "dalgınlık" (lapse) oranı ekler. Sonuç kalitesi düşüktür;
  amaç akışı uçtan uca çalıştırmaktır.

`get_model()` uygun olanı tekil (singleton) olarak döndürür.
"""
from __future__ import annotations

import math
import os
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Protocol, runtime_checkable

import chess
import numpy as np

from chessdex.measure.grid import GRID

N_GRID = GRID.size


# ---------------------------------------------------------------------------
# Protokol (CONTRACTS.md 1.1)
# ---------------------------------------------------------------------------
@runtime_checkable
class HumanMoveModel(Protocol):
    name: str
    version: str

    def move_probs(self, fen: str, elo_self: int, elo_oppo: int) -> dict[str, float]:
        """Yasal hamleler -> olasılık (toplam 1)."""
        ...

    def move_prob_grid(self, fen: str, move_uci: str, elo_oppo: int) -> np.ndarray:
        """len(GRID) uzunluklu dizi: her θ için P(move | fen, θ)."""
        ...


# ---------------------------------------------------------------------------
# Ortak yardımcılar
# ---------------------------------------------------------------------------
def _fen_key(fen: str) -> str:
    """Önbellek anahtarı: yarım hamle/hamle sayaçları hariç ilk 4 alan."""
    return " ".join(fen.split()[:4])


def _entropy(p: np.ndarray) -> float:
    p = p[p > 0]
    return float(-(p * np.log(p)).sum())


class _LRU:
    """Küçük, iş parçacığı güvenli LRU önbellek."""

    def __init__(self, maxsize: int):
        self.maxsize = maxsize
        self._d: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            if key in self._d:
                self._d.move_to_end(key)
                return self._d[key]
        return None

    def put(self, key, value):
        with self._lock:
            self._d[key] = value
            self._d.move_to_end(key)
            while len(self._d) > self.maxsize:
                self._d.popitem(last=False)

    def clear(self):
        with self._lock:
            self._d.clear()


# ---------------------------------------------------------------------------
# Sezgisel değerlendirme (malzeme + basit PST)
# ---------------------------------------------------------------------------
_VAL = {chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330,
        chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 0}

# Basitleştirilmiş PST'ler (beyaz bakış açısı, a8..h8, a7..h7, ..., a1..h1 sırası).
_PST_RAW = {
    chess.PAWN: [
        0, 0, 0, 0, 0, 0, 0, 0,
        50, 50, 50, 50, 50, 50, 50, 50,
        10, 10, 20, 30, 30, 20, 10, 10,
        5, 5, 10, 25, 25, 10, 5, 5,
        0, 0, 0, 20, 20, 0, 0, 0,
        5, -5, -10, 0, 0, -10, -5, 5,
        5, 10, 10, -20, -20, 10, 10, 5,
        0, 0, 0, 0, 0, 0, 0, 0],
    chess.KNIGHT: [
        -50, -40, -30, -30, -30, -30, -40, -50,
        -40, -20, 0, 0, 0, 0, -20, -40,
        -30, 0, 10, 15, 15, 10, 0, -30,
        -30, 5, 15, 20, 20, 15, 5, -30,
        -30, 0, 15, 20, 20, 15, 0, -30,
        -30, 5, 10, 15, 15, 10, 5, -30,
        -40, -20, 0, 5, 5, 0, -20, -40,
        -50, -40, -30, -30, -30, -30, -40, -50],
    chess.BISHOP: [
        -20, -10, -10, -10, -10, -10, -10, -20,
        -10, 0, 0, 0, 0, 0, 0, -10,
        -10, 0, 5, 10, 10, 5, 0, -10,
        -10, 5, 5, 10, 10, 5, 5, -10,
        -10, 0, 10, 10, 10, 10, 0, -10,
        -10, 10, 10, 10, 10, 10, 10, -10,
        -10, 5, 0, 0, 0, 0, 5, -10,
        -20, -10, -10, -10, -10, -10, -10, -20],
    chess.ROOK: [
        0, 0, 0, 0, 0, 0, 0, 0,
        5, 10, 10, 10, 10, 10, 10, 5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        0, 0, 0, 5, 5, 0, 0, 0],
    chess.QUEEN: [
        -20, -10, -10, -5, -5, -10, -10, -20,
        -10, 0, 0, 0, 0, 0, 0, -10,
        -10, 0, 5, 5, 5, 5, 0, -10,
        -5, 0, 5, 5, 5, 5, 0, -5,
        0, 0, 5, 5, 5, 5, 0, -5,
        -10, 5, 5, 5, 5, 5, 0, -10,
        -10, 0, 5, 0, 0, 0, 0, -10,
        -20, -10, -10, -5, -5, -10, -10, -20],
    chess.KING: [
        -30, -40, -40, -50, -50, -40, -40, -30,
        -30, -40, -40, -50, -50, -40, -40, -30,
        -30, -40, -40, -50, -50, -40, -40, -30,
        -30, -40, -40, -50, -50, -40, -40, -30,
        -20, -30, -30, -40, -40, -30, -30, -20,
        -10, -20, -20, -20, -20, -20, -20, -10,
        20, 20, 0, 0, 0, 0, 20, 20,
        20, 30, 10, 0, 0, 10, 30, 20],
}


def _build_pst():
    """_PST[renk][taş][kare] (python-chess kare indeksi: a1=0)."""
    pst = {chess.WHITE: {}, chess.BLACK: {}}
    for pt, raw in _PST_RAW.items():
        w = [0] * 64
        b = [0] * 64
        for sq in range(64):
            # raw indeksi: satır 8'den başlar
            r_idx = (7 - chess.square_rank(sq)) * 8 + chess.square_file(sq)
            w[sq] = raw[r_idx]
            b[chess.square_mirror(sq)] = raw[r_idx]
        pst[chess.WHITE][pt] = w
        pst[chess.BLACK][pt] = b
    return pst


_PST = _build_pst()

MATE_SCORE = 20000
# Kökteki en iyi skordan bu kadar kötü olduğu kesinleşen hamlenin aramasını kes.
_PRUNE_MARGIN = 800


def _static_eval(board: chess.Board, color: bool) -> int:
    """Tam statik değerlendirme, `color` bakış açısından (santipiyon)."""
    s = 0
    for sq, pc in board.piece_map().items():
        v = _VAL[pc.piece_type] + _PST[pc.color][pc.piece_type][sq]
        s += v if pc.color == color else -v
    return s


def _delta(board: chess.Board, move: chess.Move) -> int:
    """Hamlenin (push öncesi) hamle yapan taraf için değerlendirme farkı."""
    color = board.turn
    frm, to = move.from_square, move.to_square
    pt = board.piece_type_at(frm)
    pst_c = _PST[color]
    d = -pst_c[pt][frm]
    if move.promotion:
        d += _VAL[move.promotion] - _VAL[chess.PAWN] + pst_c[move.promotion][to]
    else:
        d += pst_c[pt][to]
    opp = not color
    if board.is_en_passant(move):
        cap_sq = to - 8 if color == chess.WHITE else to + 8
        d += _VAL[chess.PAWN] + _PST[opp][chess.PAWN][cap_sq]
    else:
        cpt = board.piece_type_at(to)
        if cpt is not None and board.color_at(to) == opp:
            d += _VAL[cpt] + _PST[opp][cpt][to]
    if pt == chess.KING and board.is_castling(move):
        rank = chess.square_rank(frm)
        if chess.square_file(to) > chess.square_file(frm) or board.color_at(to) == color:
            # kısa rok (chess960 gösterimi dahil)
            rf, rt = chess.square(7, rank), chess.square(5, rank)
        else:
            rf, rt = chess.square(0, rank), chess.square(3, rank)
        d += pst_c[chess.ROOK][rt] - pst_c[chess.ROOK][rf]
    return d


def _recapture_gain(board: chess.Board, sq: int) -> int:
    """Sınırlı sükunet araması: `sq` karesine en iyi geri alma kazancı (≥ 0)."""
    best = 0
    them = not board.turn
    defended = board.is_attacked_by(them, sq)
    for c in board.generate_legal_captures(to_mask=chess.BB_SQUARES[sq]):
        g = _delta(board, c)
        if defended:
            g -= _VAL[board.piece_type_at(c.from_square)]
        if g > best:
            best = g
    return best


def score_moves(fen: str) -> tuple[list[str], np.ndarray]:
    """Her yasal hamle için 2 yarım hamlelik arama skoru (hamle yapan bakışı, cp).

    Hamleler UCI'ye göre sıralıdır (belirlenimci sıra).
    """
    board = chess.Board(fen)
    me = board.turn
    base = _static_eval(board, me)
    moves = sorted(board.legal_moves, key=lambda m: m.uci())
    scores = np.empty(len(moves), dtype=np.float64)
    best_root = -math.inf
    for i, m in enumerate(moves):
        d1 = _delta(board, m)
        board.push(m)
        replies = list(board.legal_moves)
        if not replies:
            v = MATE_SCORE if board.is_check() else 0
        else:
            # önce alışlar (en düşük değeri hızla bulup budamak için)
            replies.sort(key=lambda r: 0 if board.is_capture(r) else 1)
            v = math.inf
            floor = best_root - _PRUNE_MARGIN
            for r in replies:
                d2 = _delta(board, r)
                cap = board.is_capture(r)
                board.push(r)
                leaf = base + d1 - d2
                if board.is_check():
                    if not any(board.legal_moves):
                        leaf = -MATE_SCORE
                    elif cap:
                        leaf += _recapture_gain(board, r.to_square)
                elif cap:
                    leaf += _recapture_gain(board, r.to_square)
                board.pop()
                if leaf < v:
                    v = leaf
                    if v < floor:
                        break
        board.pop()
        scores[i] = v
        if v > best_root:
            best_root = v
    return [m.uci() for m in moves], scores


# ---------------------------------------------------------------------------
# θ'ya bağlı olasılık eğrisi
# ---------------------------------------------------------------------------
# Skorlar Lichess kazanma olasılığı eğrisiyle [0,1]'e sıkıştırılır, sonra
# logit_i(θ) = (q_i - q_max) / τ(θ). τ(θ) ve dalgınlık oranı ε(θ) θ ile pürüzsüz
# ve monoton azalır. Kalibrasyon hedefi (tipik orta oyun): θ=800'de en iyi hamle
# ~%25–35, θ=2400'de ~%60–75.
_WP_K = 0.00368208
# Sıcaklık iki çapa noktasıyla tanımlanır; log τ θ'da doğrusaldır (θ ∈ [400, 3000]).
# Çapalar 8 tipik orta oyun pozisyonunda en iyi hamle olasılığının medyanına göre
# ayarlandı (θ=800 → ~%30, θ=2400 → ~%65; pozisyondan pozisyona yayılım büyüktür).
TAU_800 = 0.013
TAU_2400 = 0.0065
LAPSE_HI = 0.30   # θ=400'deki dalgınlık oranı
LAPSE_LO = 0.004  # θ=3000'deki dalgınlık oranı


def _theta_unit(theta) -> np.ndarray:
    return np.clip((np.asarray(theta, dtype=np.float64) - 400.0) / 2600.0, 0.0, 1.0)


def temperature(theta) -> np.ndarray:
    """τ(θ): log-doğrusal (geometrik) azalan sıcaklık."""
    t = np.clip(np.asarray(theta, dtype=np.float64), 400.0, 3000.0)
    return TAU_800 * (TAU_2400 / TAU_800) ** ((t - 800.0) / 1600.0)


def lapse_rate(theta) -> np.ndarray:
    """ε(θ): olasılık kütlesinin yasal hamlelere eşit dağıtılan kısmı."""
    u = _theta_unit(theta)
    return LAPSE_HI * (LAPSE_LO / LAPSE_HI) ** u


def _probs_from_scores(scores: np.ndarray, thetas: np.ndarray) -> np.ndarray:
    """(n_θ, n_hamle) olasılık matrisi; satırlar toplam 1."""
    n = scores.size
    cp = np.clip(scores, -2000.0, 2000.0)
    q = 1.0 / (1.0 + np.exp(-_WP_K * cp))
    z = (q - q.max())[None, :] / temperature(thetas)[:, None]
    e = np.exp(z)
    p = e / e.sum(axis=1, keepdims=True)
    eps = lapse_rate(thetas)[:, None]
    return (1.0 - eps) * p + eps / n


class HeuristicHumanModel:
    """Maia yokken yedek model (belirlenimci, FEN'e göre LRU önbellekli).

    Not: `elo_oppo` bu modelde etkisizdir (Maia-2 ile imza uyumu için alınır).
    """

    name = "heuristic"
    version = "h1"

    def __init__(self, cache_size: int = 4096):
        self._scores = _LRU(cache_size)
        self._grid = _LRU(cache_size)

    def scores(self, fen: str) -> tuple[list[str], np.ndarray]:
        key = _fen_key(fen)
        hit = self._scores.get(key)
        if hit is None:
            hit = score_moves(key + " 0 1")
            hit[1].setflags(write=False)
            self._scores.put(key, hit)
        return hit

    def move_probs(self, fen: str, elo_self: int, elo_oppo: int) -> dict[str, float]:
        moves, sc = self.scores(fen)
        if not moves:
            return {}
        p = _probs_from_scores(sc, np.array([float(elo_self)]))[0]
        return {m: float(x) for m, x in zip(moves, p)}

    def move_prob_grid_all(self, fen: str, elo_oppo: int = 1500) -> tuple[list[str], np.ndarray]:
        """(hamleler, (n_hamle, 261) matris): her sütun bir θ için dağılım."""
        key = _fen_key(fen)
        hit = self._grid.get(key)
        if hit is None:
            moves, sc = self.scores(fen)
            if moves:
                mat = np.ascontiguousarray(_probs_from_scores(sc, GRID).T)
            else:
                mat = np.zeros((0, N_GRID))
            mat.setflags(write=False)
            hit = (moves, mat)
            self._grid.put(key, hit)
        return hit

    def move_prob_grid(self, fen: str, move_uci: str, elo_oppo: int = 1500) -> np.ndarray:
        moves, mat = self.move_prob_grid_all(fen, elo_oppo)
        try:
            i = moves.index(move_uci)
        except ValueError:
            raise ValueError(f"yasal olmayan hamle: {move_uci} @ {fen}") from None
        return mat[i].copy()

    def entropy(self, fen: str, elo: int) -> float:
        """Hamle dağılımının entropisi (nat) — pozisyon karmaşıklığı."""
        p = np.array(list(self.move_probs(fen, elo, elo).values()))
        return _entropy(p) if p.size else 0.0


# ---------------------------------------------------------------------------
# Maia-2 adaptörü
# ---------------------------------------------------------------------------
# Maia-2 Elo'yu 11 kovaya ayırır: <1100 tek kova, 1100..1999 arası 100'lük kovalar, ≥2000 tek kova.
# Izgara için kova merkezlerinde çıkarım yapılır; θ merkezler arasında log-olasılık uzayında doğrusal
# interpole edilir, uçların dışı sabit tutulur (Maia-2 orada bilgi taşımaz; olabilirlik düzdür).
# Açık uçlu kovaların merkezi, Lichess 2026-09 rapid oyunlarındaki gerçek ortalamadır
# (26.418 oyuncu-oyun): <1100 → 903, ≥2000 → 2137. İç kovalar: 1150, 1250, ..., 1950.
MAIA_CENTERS = np.array([903.0, *np.arange(1150, 1951, 100), 2137.0])
_MAIA_FLOOR = 1e-6

# Uç kovaların ötesine uzatma: θ < 903 ve θ > 2137'de log-olasılık, son iki kovanın eğimi × κ ile en fazla
# MAX_EXT Elo boyunca sürdürülür, sonra sabit kalır; ardından hamleler üzerinde yeniden normalize edilir.
# κ = 0 → eski davranış (uçların dışı düz). Değerler geriye dönük testte seçilir (docs/results/extremes.md).
EXTRAP_LOW = 0.0
EXTRAP_HIGH = 0.5
MAX_EXT = 600.0


def interp_matrix(kappa_low: float = None, kappa_high: float = None, max_ext: float = None,
                  grid: np.ndarray = GRID) -> np.ndarray:
    """(G, 11) matris: log P(θ) = M @ log P(merkezler). Aradeğerleme ve uzatma θ'da doğrusal olduğu için tek matris."""
    kl = EXTRAP_LOW if kappa_low is None else kappa_low
    kh = EXTRAP_HIGH if kappa_high is None else kappa_high
    mx = MAX_EXT if max_ext is None else max_ext
    c = MAIA_CENTERS
    M = np.zeros((grid.size, c.size))
    for g, th in enumerate(grid):
        if th <= c[0]:
            d = max(th, c[0] - mx) - c[0]                        # ≤ 0
            s = kl * d / (c[1] - c[0])
            M[g, 0], M[g, 1] = 1.0 - s, s
        elif th >= c[-1]:
            d = min(th, c[-1] + mx) - c[-1]                      # ≥ 0
            s = kh * d / (c[-1] - c[-2])
            M[g, -1], M[g, -2] = 1.0 + s, -s
        else:
            j = int(np.searchsorted(c, th)) - 1
            t = (th - c[j]) / (c[j + 1] - c[j])
            M[g, j], M[g, j + 1] = 1.0 - t, t
    return M


def centers_to_grid(L: np.ndarray, M: np.ndarray | None = None) -> np.ndarray:
    """L (n_hamle, 11) log olasılık → (n_hamle, G) olasılık; her θ'da hamleler üzerinde normalize."""
    logp = L @ (interp_matrix() if M is None else M).T
    logp -= logp.max(axis=0, keepdims=True)
    mat = np.exp(logp)
    return mat / mat.sum(axis=0, keepdims=True)


MAIA_WEIGHTS_DIR = Path(__file__).resolve().parents[3] / "tools" / "maia2_models"


class Maia2Model:
    """`maia2` paketi (0.11.0, MIT) üzerinden gerçek Maia-2 (rapid, CPU, FP32).

    Paketin `inference_each`'i kullanılmaz: olasılıkları 4 ondalığa yuvarlar (küçük olasılıklar 0 olur,
    olabilirliği bozar) ve her Elo için ayrı çağrı ister. Bunun yerine paketin ön işlemesi + modeli doğrudan,
    11 Elo kovası tek toplu ileri geçişte çalıştırılır. Siyah sırada tahta paket tarafından aynalanır;
    hamleler `mirror_move` ile geri çevrilir.
    """

    name = "maia2"
    version = "maia2-0.11.0-rapid"

    def __init__(self, game_type: str = "rapid", device: str = "cpu", cache_size: int = 2048):
        import torch
        from maia2 import inference, model  # tembel içe aktarma
        from maia2.utils import mirror_move

        torch.set_num_threads(int(os.environ.get("CHESSDEX_TORCH_THREADS", "4")))
        self._torch = torch
        self._inference = inference
        self._mirror = mirror_move
        self._model = model.from_pretrained(type=game_type, device=device, save_root=str(MAIA_WEIGHTS_DIR))
        self._model.eval()
        self._prepared = inference.prepare()
        self._lock = threading.Lock()
        self._cache = _LRU(cache_size)
        self._grid = _LRU(cache_size)

    @classmethod
    def available(cls) -> bool:
        try:
            import importlib.util

            return importlib.util.find_spec("maia2") is not None
        except Exception:  # pragma: no cover
            return False

    @staticmethod
    def _clamp_elo(elo: float) -> int:
        return int(min(max(elo, MAIA_CENTERS[0]), MAIA_CENTERS[-1]))

    def forward(self, fen: str, elos_self, elo_oppo) -> tuple[list[str], np.ndarray]:
        """Yuvarlamasız Maia-2: (UCI sıralı yasal hamleler, (len(elos_self), n_hamle) olasılık matrisi).
        `elo_oppo` tek sayı ya da `elos_self` ile aynı uzunlukta dizi olabilir."""
        torch = self._torch
        all_moves_dict, elo_dict, rev = self._prepared
        board_t, _, _, legal = self._inference.preprocessing(fen, 1500, 1500, elo_dict, all_moves_dict)
        from maia2.utils import map_to_category

        cats = [map_to_category(int(e), elo_dict) for e in elos_self]
        n = len(cats)
        oppo = list(elo_oppo) if np.ndim(elo_oppo) else [elo_oppo] * n
        ocats = [map_to_category(int(e), elo_dict) for e in oppo]
        with self._lock, torch.no_grad():
            logits, _, _ = self._model(board_t.unsqueeze(0).expand(n, *board_t.shape),
                                       torch.tensor(cats), torch.tensor(ocats))
            probs = self._inference._masked_softmax(logits, legal.unsqueeze(0).expand(n, -1))
        idx = legal.nonzero(as_tuple=True)[0]
        black = fen.split()[1] == "b"
        names = [self._mirror(rev[int(i)]) if black else rev[int(i)] for i in idx]
        P = probs[:, idx].double().numpy()
        order = np.argsort(names)
        return [names[i] for i in order], P[:, order]

    def _raw(self, fen: str, elo_self: int, elo_oppo: int) -> tuple[list[str], np.ndarray]:
        """Yasal hamleler (UCI sıralı) ve Maia-2 olasılıkları (taban + normalize)."""
        es, eo = self._clamp_elo(elo_self), self._clamp_elo(elo_oppo)
        key = (_fen_key(fen), es, eo)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        if not any(chess.Board(fen).legal_moves):
            hit = ([], np.zeros(0))
        else:
            moves, P = self.forward(fen, [es], eo)
            p = P[0] + _MAIA_FLOOR
            hit = (moves, p / p.sum())
        self._cache.put(key, hit)
        return hit

    def move_probs(self, fen: str, elo_self: int, elo_oppo: int) -> dict[str, float]:
        moves, p = self._raw(fen, elo_self, elo_oppo)
        return {m: float(x) for m, x in zip(moves, p)}

    def move_prob_grid_all(self, fen: str, elo_oppo: int) -> tuple[list[str], np.ndarray]:
        key = (_fen_key(fen), self._clamp_elo(elo_oppo))
        hit = self._grid.get(key)
        if hit is not None:
            return hit
        if not any(chess.Board(fen).legal_moves):
            hit = ([], np.zeros((0, N_GRID)))
        else:
            moves, P = self.forward(fen, MAIA_CENTERS, self._clamp_elo(elo_oppo))   # (11, n_hamle)
            hit = (moves, centers_to_grid(np.log(P.T + _MAIA_FLOOR)))
        hit[1].setflags(write=False)
        self._grid.put(key, hit)
        return hit

    def move_prob_grid(self, fen: str, move_uci: str, elo_oppo: int) -> np.ndarray:
        moves, mat = self.move_prob_grid_all(fen, elo_oppo)
        try:
            i = moves.index(move_uci)
        except ValueError:
            raise ValueError(f"yasal olmayan hamle: {move_uci} @ {fen}") from None
        return mat[i].copy()

    def entropy(self, fen: str, elo: int) -> float:
        _, p = self._raw(fen, elo, elo)
        return _entropy(p) if p.size else 0.0


# ---------------------------------------------------------------------------
# Fabrika, bot yardımcıları
# ---------------------------------------------------------------------------
_MODEL = None
_MODEL_LOCK = threading.Lock()


def get_model():
    """Maia-2 varsa (ve CHESSDEX_HUMAN_MODEL != 'heuristic') onu, yoksa yedeği döndürür."""
    global _MODEL
    if _MODEL is None:
        with _MODEL_LOCK:
            if _MODEL is None:
                choice = os.environ.get("CHESSDEX_HUMAN_MODEL", "").strip().lower()
                m = None
                if choice != "heuristic" and Maia2Model.available():
                    try:
                        m = Maia2Model()
                    except Exception:
                        m = None  # ağırlıklar yüklenemezse yedeğe düş
                _MODEL = m if m is not None else HeuristicHumanModel()
    return _MODEL


def _reset_model_for_tests() -> None:
    global _MODEL
    with _MODEL_LOCK:
        _MODEL = None


def sample_move(model, fen: str, elo: int, oppo: int, rng: np.random.Generator) -> str:
    """Bot hamlesi: dağılımdan örnekleme (argmax değil). Sıra UCI'ye göre sabit."""
    probs = model.move_probs(fen, elo, oppo)
    if not probs:
        raise ValueError("yasal hamle yok")
    moves = sorted(probs)
    p = np.array([probs[m] for m in moves], dtype=np.float64)
    p /= p.sum()
    return moves[int(rng.choice(len(moves), p=p))]


THINK_MIN_MS = 1000
THINK_MAX_MS = 8000


def think_time_ms(fen: str, entropy: float, rng: np.random.Generator) -> int:
    """Yapay düşünme süresi (1–8 sn): normalize entropi yüksekse daha uzun."""
    n = chess.Board(fen).legal_moves.count()
    if n <= 1:
        return THINK_MIN_MS
    h = min(max(entropy / math.log(n), 0.0), 1.0)
    base = THINK_MIN_MS + (THINK_MAX_MS - THINK_MIN_MS) * h ** 1.5
    jitter = math.exp(float(rng.normal(0.0, 0.25)))
    return int(min(max(base * jitter, THINK_MIN_MS), THINK_MAX_MS))
