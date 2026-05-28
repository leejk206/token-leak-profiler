"""Shared computation helpers for analyzers."""
from __future__ import annotations
from statistics import mean, stdev


def estimate_stable_prefix(actual_cr_values: list[int]) -> int | None:
    """Given the cache_read values observed at each invalidation event,
    estimate the stable system-prompt prefix size.

    Returns the mean if all values are tightly clustered (std-dev < 1% of mean),
    else None — meaning the prefix isn't stable enough to identify.

    A single value is treated as a stable prefix if it is non-zero.
    Requires ≥ 2 values to compute std-dev; with exactly 1 value the
    cluster check is skipped and the value itself is returned (if > 0).
    """
    if len(actual_cr_values) == 0:
        return None
    if len(actual_cr_values) == 1:
        return actual_cr_values[0] if actual_cr_values[0] > 0 else None
    m = mean(actual_cr_values)
    if m == 0:
        return None
    s = stdev(actual_cr_values)
    if s / m < 0.01:
        return int(m)
    return None
