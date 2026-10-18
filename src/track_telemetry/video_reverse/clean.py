"""OCR speed cleaning: median reject + gap interp. Pure stdlib.

Physics bound: <3mph per 0.1s at 10Hz, so a wide median window never smears
real transitions. Burst misreads (e.g. sustained 7->9) outvote narrow windows:
use window 9, threshold 5mph. Residual burst zones still need frame truth.
"""

from __future__ import annotations

import statistics


def reject_outliers(series, window=9, threshold=5.0):
    """Replace samples >threshold from local median with None. Returns (base, n_rejected)."""
    n = len(series)
    med = []
    half = window // 2
    for i in range(n):
        w = [v for v in series[max(0, i - half):min(n, i + half + 1)] if v is not None]
        med.append(statistics.median(w) if w else None)
    base, rej = [], 0
    for i, v in enumerate(series):
        if v is not None and med[i] is not None and abs(v - med[i]) > threshold:
            rej += 1
            base.append(None)
        else:
            base.append(v)
    return base, rej


def interp_gaps(base):
    """Linear interp over None runs; forward/backward fill at edges."""
    n = len(base)
    out = list(base)
    for i in range(n):
        if out[i] is None:
            left = next((out[j] for j in range(i - 1, -1, -1) if out[j] is not None), None)
            right = next((out[j] for j in range(i + 1, n) if out[j] is not None), None)
            out[i] = left if right is None else right if left is None else (left + right) / 2
    return out


def clean_speed_series(series, window=9, threshold=5.0):
    """Full clean: reject then interp. Returns (cleaned, n_rejected, n_filled)."""
    base, rej = reject_outliers(series, window, threshold)
    filled = sum(1 for v in base if v is None)
    out = interp_gaps(base)
    return [round(v, 1) if v is not None else None for v in out], rej, filled
