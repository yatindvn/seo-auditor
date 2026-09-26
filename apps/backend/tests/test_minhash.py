"""MinHash + LSH: duplicate detection that fits in memory at 5000 pages.

A full shingle set is ~50 KB per page, so 5000 pages cost 160-320 MB held at
once. A 128-value signature is 512 bytes. The trade is exactness -- similarity
becomes an estimate -- which is why app/analysis/analysis.py keeps the exact
path for crawls of 500 pages or fewer and uses this only above that.
"""

import random

from app.analysis import minhash
from app.analysis.analysis import near_duplicate_content

WORDS = "espresso machine grinder burr tamper portafilter basket shot pull crema".split()


def _document(seed, length=400):
    rng = random.Random(seed)
    return " ".join(rng.choice(WORDS) for _ in range(length))


def test_signature_is_512_bytes():
    """128 x 32-bit. The memory claim this whole design rests on, pinned by a
    test rather than by a comment."""
    assert len(minhash.signature("some text with several words in it")) == 512


def test_signature_of_empty_text_is_none():
    assert minhash.signature("") is None
    assert minhash.signature("   ") is None


def test_signature_is_stable_across_calls():
    """Signatures are compared between worker processes and across runs, so the
    permutations cannot come from Python's per-process randomised hash()."""
    text = _document(3)

    assert minhash.signature(text) == minhash.signature(text)


def test_identical_documents_estimate_as_identical():
    text = _document(1)

    assert minhash.estimated_jaccard(minhash.signature(text), minhash.signature(text)) == 1.0


def test_unrelated_documents_estimate_far_below_the_threshold():
    a = "the quick brown fox jumps over the lazy dog " * 40
    b = "financial results for the fourth quarter exceeded expectations " * 40

    assert minhash.estimated_jaccard(minhash.signature(a), minhash.signature(b)) < 0.2


def test_estimate_is_close_to_the_true_jaccard():
    """The estimator has to be roughly right, not merely ordered correctly.
    Tolerance is the documented error band at 128 permutations, not a number
    chosen to make this pass."""
    a = _document(11)
    b = a.rsplit(" ", 40)[0] + " " + _document(12, length=40)

    def shingles(text):
        words = text.lower().split()
        return {" ".join(words[i:i + 5]) for i in range(len(words) - 4)}

    sa, sb = shingles(a), shingles(b)
    true_jaccard = len(sa & sb) / len(sa | sb)
    estimate = minhash.estimated_jaccard(minhash.signature(a), minhash.signature(b))

    assert abs(estimate - true_jaccard) < 0.15, (
        f"estimate {estimate:.3f} vs true {true_jaccard:.3f}"
    )


def test_near_duplicates_finds_the_pair_the_exact_path_finds():
    """Recall is the property that matters: a pair the exact implementation
    reports well above the threshold must not be missed by the approximation."""
    base = _document(7)
    tweaked = base.rsplit(" ", 20)[0] + " grinder burr tamper basket shot"
    pages = [
        {"url": "https://example.com/a", "text": base},
        {"url": "https://example.com/b", "text": tweaked},
        {"url": "https://example.com/c", "text": _document(99)},
    ]
    exact = near_duplicate_content(pages)
    assert exact, "fixture must contain a genuine duplicate pair for this to test anything"

    signatures = {p["url"]: minhash.signature(p["text"]) for p in pages}
    approximate = minhash.near_duplicates(signatures)

    exact_pairs = {(p["url_a"], p["url_b"]) for p in exact}
    approximate_pairs = {(p["url_a"], p["url_b"]) for p in approximate}
    assert exact_pairs <= approximate_pairs, (
        f"MinHash missed a pair the exact path found: {exact_pairs - approximate_pairs}"
    )


def test_unrelated_documents_are_not_reported_as_duplicates():
    signatures = {f"https://example.com/{i}": minhash.signature(_document(i)) for i in range(8)}

    assert minhash.near_duplicates(signatures) == []


def test_reported_pairs_carry_the_shape_the_exact_path_returns():
    """analysis.find_near_duplicates returns either path's output to the same
    caller, so the two must agree on shape."""
    text = _document(5)
    signatures = {"https://example.com/a": minhash.signature(text),
                  "https://example.com/b": minhash.signature(text)}

    pair = minhash.near_duplicates(signatures)[0]

    assert set(pair) == {"url_a", "url_b", "similarity"}
    assert pair["url_a"] < pair["url_b"], "pairs are emitted in a stable order"
    assert isinstance(pair["similarity"], float)


def test_banding_beats_comparing_every_pair():
    """The point of LSH: candidate generation must be sub-quadratic, or this is
    just the old algorithm with smaller sets."""
    signatures = {f"https://example.com/{i}": minhash.signature(_document(i)) for i in range(200)}

    candidates = minhash.candidate_pairs(signatures)

    assert len(candidates) < 200 * 199 / 2 / 10


def test_none_signatures_are_ignored_not_crashed_on():
    """A page with no text has no signature; it arrives here alongside pages
    that do."""
    signatures = {
        "https://example.com/empty": None,
        "https://example.com/a": minhash.signature(_document(1)),
    }

    assert minhash.near_duplicates(signatures) == []
