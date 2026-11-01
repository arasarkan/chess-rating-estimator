"""θ ızgarası: Lichess rapid skalasında 400–3000, 10'ar Elo (261 nokta)."""
import numpy as np

GRID = np.arange(400, 3001, 10, dtype=np.float64)
N = GRID.size
assert N == 261
