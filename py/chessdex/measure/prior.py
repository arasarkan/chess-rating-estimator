"""Önsel dağılımlar (log uzayında, GRID üzerinde)."""
from __future__ import annotations

import numpy as np

from .grid import GRID

DEFAULT_MEAN = 1500.0
DEFAULT_SD = 800.0       # 450 uçlarda ortalamaya çekiyordu (docs/results/extremes.md)

# Anket etkileri: pilot verisiyle öğrenilecek; şimdilik zayıf (Elo kaydırması, sd çarpanı).
# Anahtarlar ve değerler web formuyla birebir aynıdır (apps/web/app/page.tsx; test_survey_contract.py denetler).
SURVEY_EFFECTS = {
    "years_playing": {"lt1": -250, "1-3": -100, "3-10": 50, "gt10": 150},
    "games_per_week": {"0": -100, "1-5": -30, "6-20": 30, "gt20": 100},
    "tournament": {"none": -100, "club": 100, "rated": 300},
}
SURVEY_SHRINK = 0.5   # anket etkisini zayıf tut
SURVEY_SD = 700.0     # anket cevaplandıysa önsel biraz daralır (450→400 oranıyla; doğrulanmadı)


def normal_log_prior(mean: float, sd: float) -> np.ndarray:
    lp = -0.5 * ((GRID - mean) / sd) ** 2
    return lp - np.logaddexp.reduce(lp)


def default_prior() -> np.ndarray:
    return normal_log_prior(DEFAULT_MEAN, DEFAULT_SD)


def survey_prior(survey: dict | None) -> np.ndarray:
    if not survey:
        return default_prior()
    shift, answered = 0.0, 0
    for key, table in SURVEY_EFFECTS.items():
        v = survey.get(key)
        if v in table:
            shift += table[v]
            answered += 1
    if not answered:
        return default_prior()
    return normal_log_prior(DEFAULT_MEAN + SURVEY_SHRINK * shift, SURVEY_SD)
