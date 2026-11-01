"""JSONL senaryo bankası yükleyici ve yerleşik demo bankası."""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path

from .models import BankItem

DEMO_PATH = Path(__file__).resolve().parents[2] / "data" / "demo_bank.jsonl"


def load_items(path: str | Path) -> list[BankItem]:
    """JSONL dosyasından BankItem listesi (boş satırlar atlanır)."""
    items: list[BankItem] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                items.append(BankItem.from_dict(json.loads(line)))
    return items


@lru_cache(maxsize=1)
def _demo_cached() -> tuple[BankItem, ...]:
    if DEMO_PATH.exists():
        return tuple(load_items(DEMO_PATH))
    from .demo_gen import generate  # dosya yoksa yeniden üret (yavaş)

    return tuple(generate())


def demo_items() -> list[BankItem]:
    """Lichess indirmesi olmadan uygulamanın çalışması için demo bankası (kopya döner)."""
    return copy.deepcopy(list(_demo_cached()))
