from unittest.mock import patch

from tlp.tokenizer.local import count_tokens


def test_empty_string():
    assert count_tokens("") == 0


def test_short_text():
    # chars/4 ceil — "hello" → 5 chars → 2
    assert count_tokens("hello") == 2


def test_exact_multiple_of_four():
    assert count_tokens("aaaa") == 1
    assert count_tokens("aaaaaaaa") == 2


def test_unicode_counted_by_chars_not_bytes():
    # 4 hangul chars → 1 token (chars/4)
    assert count_tokens("가나다라") == 1


def test_none_and_dict_safe():
    # Helper variant for non-string callers
    from tlp.tokenizer.local import count_tokens_of
    assert count_tokens_of(None) == 0
    assert count_tokens_of({"a": 1}) > 0  # JSON-serialized


def test_verify_disabled_returns_none_drift():
    from tlp.tokenizer.verify import compute_drift_pct
    # No API key / module missing → graceful None
    with patch("tlp.tokenizer.verify._count_via_anthropic", side_effect=RuntimeError("no key")):
        assert compute_drift_pct(local_total=1000, sample_messages=[]) is None


def test_verify_returns_drift_pct():
    from tlp.tokenizer.verify import compute_drift_pct
    with patch("tlp.tokenizer.verify._count_via_anthropic", return_value=1100):
        drift = compute_drift_pct(local_total=1000, sample_messages=[{"role": "user", "content": "hi"}])
        # 1100 vs local 1000 → +10%
        assert drift == 10.0


def test_verify_zero_local_safe():
    from tlp.tokenizer.verify import compute_drift_pct
    with patch("tlp.tokenizer.verify._count_via_anthropic", return_value=0):
        assert compute_drift_pct(local_total=0, sample_messages=[]) == 0.0
