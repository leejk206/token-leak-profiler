from __future__ import annotations
from pathlib import Path
from typing import Any
import yaml

from tlp.types import PricingTable

_HERE = Path(__file__).parent
_DEFAULTS_PATH = _HERE / "defaults.yaml"
_PRICING_PATH = _HERE / "pricing.yaml"


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_defaults(override_path: Path | None = None) -> dict[str, Any]:
    with _DEFAULTS_PATH.open() as f:
        base = yaml.safe_load(f) or {}
    if override_path:
        with override_path.open() as f:
            ov = yaml.safe_load(f) or {}
        return _deep_merge(base, ov)
    return base


def load_pricing(override_path: Path | None = None, model: str | None = None) -> PricingTable:
    path = override_path or _PRICING_PATH
    with path.open() as f:
        data = yaml.safe_load(f)
    model_id = model or data["default"]
    m = data["models"][model_id]
    return PricingTable(
        input_per_mtok=float(m["input_per_mtok"]),
        output_per_mtok=float(m["output_per_mtok"]),
        cache_read_per_mtok=float(m["cache_read_per_mtok"]),
        cache_creation_per_mtok=float(m["cache_creation_per_mtok"]),
    )
