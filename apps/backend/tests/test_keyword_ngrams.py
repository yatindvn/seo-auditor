"""_phrases_from_text must produce the same phrases, however it gets there."""

from collections import Counter

import pytest

from app.seo import keyword_extraction
from app.seo.keyword_extraction import _is_content_word, _tokenize


def _reference(text):
    """The original implementation, kept verbatim as the oracle."""
    tokens = _tokenize(text)
    phrases = []
    for n in (1, 2, 3):
        for i in range(len(tokens) - n + 1):
            gram = tokens[i:i + n]
            if all(_is_content_word(t) for t in gram):
                phrases.append(" ".join(gram))
    return phrases


CASES = [
    "",
    "the",
    "espresso",
    "the espresso machine",
    "best espresso machine reviews and buying guide for the home",
    "a an the and or but",
    "grinder grinder grinder grinder",
    "it's the barista's choice, isn't it",
    "on top of the best burr grinders of 2026 and beyond the hype",
    "x yy zzz long words only here",
]


@pytest.mark.parametrize("text", CASES)
def test_same_phrases_as_the_original(text):
    assert Counter(keyword_extraction._phrases_from_text(text)) == Counter(_reference(text))


def test_each_word_is_checked_once(monkeypatch):
    """The point of the change: one stop-word check per token, not one per
    token per n-gram it belongs to."""
    calls = []
    original = keyword_extraction._is_content_word
    monkeypatch.setattr(keyword_extraction, "_is_content_word",
                        lambda t: calls.append(t) or original(t))

    keyword_extraction._phrases_from_text("best espresso machine reviews guide")

    assert len(calls) == 5
