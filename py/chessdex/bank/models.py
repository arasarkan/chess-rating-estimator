"""Senaryo bankası veri modeli (BankItem) ve başlangıç parametre sabitleri."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

KINDS = ("tactics", "endgame", "defense", "positional")

# Zorluk eşlemesi b = ALPHA + BETA * bulmaca_rating. Pilot verisiyle yeniden öğrenilecek.
B_MAPPING = {"alpha": -200.0, "beta": 1.0}

# Tahmin şansı: hamle girişli senaryolar için sabit; çoktan seçmelide 1/seçenek sayısı.
C_MOVE_ENTRY = 0.02

# Süre verisi yokken hızlı/yavaş eşiği için sezgisel sınırlar (ms).
FAST_MS_MIN = 4_000
FAST_MS_MAX = 90_000


def initial_b(puzzle_rating: float, alpha: float | None = None, beta: float | None = None) -> float:
    """Bulmaca rating'inden başlangıç zorluğu b."""
    a = B_MAPPING["alpha"] if alpha is None else alpha
    bt = B_MAPPING["beta"] if beta is None else beta
    return float(a + bt * puzzle_rating)


def default_time_fast_ms(puzzle_rating: float, n_half_moves: int, multiple_choice: bool = False) -> int:
    """Süre dağılımı yokken hızlı/yavaş eşiği: oyuncu hamle sayısı ve zorlukla artar."""
    n_player = max(1, (n_half_moves + 1) // 2)
    base = 6_000 + 7_000 * (n_player - 1)
    # Zorluk çarpanı: 600 → ~0.8, 1500 → ~1.4, 2600 → ~2.6 (üstel artış)
    factor = 0.8 * math.exp((float(puzzle_rating) - 600.0) / 1700.0)
    if multiple_choice:
        factor *= 0.8
    ms = int(round(base * factor / 100.0) * 100)
    return max(FAST_MS_MIN, min(FAST_MS_MAX, ms))


@dataclass
class BankItem:
    """Tek senaryo. `fen` oyuncunun çözeceği pozisyon; `solution` oyuncu perspektifinde UCI listesi
    (çift indeksler oyuncu, tek indeksler rakibin sunucuca uygulanan cevapları)."""

    id: str
    source: str
    fen: str
    solution: list[str]
    kind: str = "tactics"
    themes: list[str] = field(default_factory=list)
    puzzle_rating: float = 1500.0
    rating_dev: float | None = None
    n_plays: int | None = None
    choices: list[str] | None = None
    b: float | None = None
    a: float = 1.0
    c: float | None = None
    time_fast_ms: int | None = None
    move_scores: dict[str, int] | None = None  # pozisyonel kademeli puanlar (0–3)
    offsets: list[float] | None = None         # senaryoya özgü kademe eşikleri (b'ye göre, artan); yoksa varsayılan
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"geçersiz tür: {self.kind}")
        if not self.solution:
            raise ValueError("çözüm boş olamaz")
        self.solution = list(self.solution)
        self.themes = list(self.themes)
        if self.b is None:
            self.b = initial_b(self.puzzle_rating)
        if self.c is None:
            self.c = (1.0 / len(self.choices)) if self.choices else C_MOVE_ENTRY
        if self.time_fast_ms is None:
            self.time_fast_ms = default_time_fast_ms(
                self.puzzle_rating, len(self.solution), multiple_choice=bool(self.choices)
            )

    @property
    def player_moves(self) -> list[str]:
        """Oyuncunun yapması gereken hamleler (çift indeksler)."""
        return self.solution[0::2]

    @property
    def n_player_moves(self) -> int:
        return (len(self.solution) + 1) // 2

    @property
    def graded(self) -> bool:
        """Kademeli (0–3) puanlanan senaryo mu?"""
        return bool(self.move_scores)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BankItem":
        known = {f for f in cls.__dataclass_fields__}
        kw = {k: v for k, v in d.items() if k in known}
        if kw.get("move_scores") is not None:
            kw["move_scores"] = {str(k): int(v) for k, v in kw["move_scores"].items()}
        return cls(**kw)
