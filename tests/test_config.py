from pathlib import Path
from tlp.config import load_defaults, load_pricing
from tlp.types import PricingTable


def test_load_defaults_returns_dict_with_all_levers():
    d = load_defaults()
    assert set(d.keys()) >= {
        "stale_context", "redundant_restatement", "tool_schema_bloat",
        "verbose_tool_results", "reasoning_overrun", "format_boilerplate",
        "report",
    }
    assert d["stale_context"]["stale_after_turns"] == 5


def test_load_pricing_default_model():
    p = load_pricing()
    assert isinstance(p, PricingTable)
    assert p.input_per_mtok == 3.0
    assert p.output_per_mtok == 15.0


def test_load_defaults_with_override(tmp_path: Path):
    override = tmp_path / "custom.yaml"
    override.write_text("stale_context:\n  stale_after_turns: 99\n")
    d = load_defaults(override)
    assert d["stale_context"]["stale_after_turns"] == 99
    # other keys still present from base
    assert "redundant_restatement" in d


def test_load_pricing_with_override(tmp_path: Path):
    override = tmp_path / "p.yaml"
    override.write_text(
        "models:\n"
        "  claude-sonnet-4-6:\n"
        "    input_per_mtok: 99.0\n"
        "    output_per_mtok: 100.0\n"
        "    cache_read_per_mtok: 1.0\n"
        "    cache_creation_per_mtok: 2.0\n"
        "default: claude-sonnet-4-6\n"
    )
    p = load_pricing(override)
    assert p.input_per_mtok == 99.0
