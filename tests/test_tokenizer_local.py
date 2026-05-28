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
