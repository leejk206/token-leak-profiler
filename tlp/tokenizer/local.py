"""Local token approximation: chars / 4, rounded up.

This is intentionally coarse — analyzers compare relative quantities, so absolute
accuracy isn't critical. For ground truth, use --verify mode (tokenizer.verify).
"""
from __future__ import annotations
import json
import math
from typing import Any


def count_tokens(text: str) -> int:
    if not text:
        return 0
    return math.ceil(len(text) / 4)


def count_tokens_of(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return count_tokens(value)
    return count_tokens(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
