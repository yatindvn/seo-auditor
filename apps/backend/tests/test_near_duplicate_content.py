"""near_duplicate_content must return the same pairs as brute force, quickly.

The original implementation compared every page against every other -- its own
docstring said "fine for a few hundred pages, not designed for huge sites". At
the Full Site Crawl preset's 5000 pages that is ~12.5 million pairwise Jaccard
computations, which pinned a CPU core indefinitely and meant the audit never
returned.

These tests pin two things: the results must be *identical* to brute force (this
is an exact optimisation, not an approximation), and it must scale.
"""

import random
import time

from app.analysis import analysis, minhash


def _brute_force(page_data, shingle_size=5, threshold=0.85):
    """The original O(n^2) algorithm, kept as the correctness oracle."""
    def shingles(text):
        words = text.lower().split()
        return {
            " ".join(words[i:i + shingle_size])
            for i in range(max(len(words) - shingle_size + 1, 1))
        }

    sets = {p["url"]: shingles(p.get("text", "")) for p in page_data if p.get("text")}
    urls = list(sets.keys())
    pairs = []
    for i in range(len(urls)):
        for j in range(i + 1, len(urls)):
            a, b = sets[urls[i]], sets[urls[j]]
            if not a or not b:
                continue
            sim = len(a & b) / len(a | b)
            if sim >= threshold:
                pairs.append({"url_a": urls[i], "url_b": urls[j], "similarity": round(sim, 3)})
    return pairs


def _norm(pairs):
    """Order-independent, so the two implementations can be compared directly."""
    return sorted((p["url_a"], p["url_b"], p["similarity"]) for p in pairs)


def _page(i, text):
    return {"url": f"https://example.com/{i}", "text": text}


def test_identical_pages_are_reported():
    body = "the quick brown fox jumps over the lazy dog and keeps on running for a while"
    pages = [_page(1, body), _page(2, body)]

    out = analysis.near_duplicate_content(pages)

    assert len(out) == 1
    assert out[0]["similarity"] == 1.0


def test_unrelated_pages_are_not_reported():
    pages = [
        _page(1, "espresso machines grinders and burr settings for home baristas everywhere"),
        _page(2, "quarterly financial results revenue growth and shareholder returns this year"),
    ]

    assert analysis.near_duplicate_content(pages) == []


def test_pages_without_text_are_skipped():
    pages = [_page(1, ""), _page(2, ""), _page(3, "some genuine content here to compare against")]

    assert analysis.near_duplicate_content(pages) == []


def test_near_but_below_threshold_is_excluded():
    base = " ".join(f"word{i}" for i in range(100))
    changed = " ".join(f"word{i}" if i % 3 else f"other{i}" for i in range(100))
    pages = [_page(1, base), _page(2, changed)]

    assert analysis.near_duplicate_content(pages) == _brute_force(pages)


def test_matches_brute_force_on_a_mixed_corpus():
    """The property that matters: this is an exact optimisation, so the output
    must equal the original algorithm's output, pair for pair."""
    rng = random.Random(1234)
    vocab = [f"term{i}" for i in range(400)]
    pages = []
    for i in range(60):
        body = " ".join(rng.choice(vocab) for _ in range(120))
        pages.append(_page(i, body))
        if i % 7 == 0:                      # exact duplicate
            pages.append(_page(f"{i}-copy", body))
        if i % 11 == 0:                     # near duplicate
            words = body.split()
            words[3] = "swapped"
            pages.append(_page(f"{i}-near", " ".join(words)))

    assert _norm(analysis.near_duplicate_content(pages)) == _norm(_brute_force(pages))


def test_scales_to_a_full_site_crawl():
    """2000 pages must finish in seconds. The original took ~2 million pairwise
    set operations here and minutes of CPU; at the 5000-page preset it never
    returned at all."""
    rng = random.Random(99)
    vocab = [f"w{i}" for i in range(2000)]
    pages = [
        _page(i, " ".join(rng.choice(vocab) for _ in range(150)))
        for i in range(2000)
    ]
    # A handful of real duplicates so it cannot pass by finding nothing.
    pages.append(_page("dup-a", pages[0]["text"]))
    pages.append(_page("dup-b", pages[1]["text"]))

    started = time.monotonic()
    out = analysis.near_duplicate_content(pages)
    elapsed = time.monotonic() - started

    assert elapsed < 30, f"took {elapsed:.1f}s for 2000 pages"
    found = {(p["url_a"], p["url_b"]) for p in out}
    assert ("https://example.com/0", "https://example.com/dup-a") in found
    assert ("https://example.com/1", "https://example.com/dup-b") in found


# --- Picking a path by crawl size ------------------------------------------
#
# Above a few hundred pages, holding a full shingle set per page costs hundreds
# of megabytes, so detection switches to MinHash estimates. Below it, exact
# results are affordable and strictly better, so nothing changes for the crawl
# sizes that have always worked.


def _pages(count, text_for=lambda i: None):
    return [
        {"url": f"https://example.com/{i}",
         "text": text_for(i) or f"unique filler text number {i} " * 30}
        for i in range(count)
    ]


def test_small_crawls_use_the_exact_path():
    pairs, mode = analysis.find_near_duplicates(_pages(10), signatures={})

    assert mode == "exact"
    assert pairs == []


def test_large_crawls_switch_to_minhash():
    pages = _pages(analysis.EXACT_PATH_MAX_PAGES + 1)
    signatures = {p["url"]: minhash.signature(p["text"]) for p in pages}

    _, mode = analysis.find_near_duplicates(pages, signatures=signatures)

    assert mode == "minhash"


def test_minhash_mode_still_reports_a_real_duplicate_pair():
    """Switching paths must not switch the feature off."""
    shared = "the same paragraph repeated across two separate pages " * 40
    pages = _pages(analysis.EXACT_PATH_MAX_PAGES)
    pages += [
        {"url": "https://example.com/dupe-a", "text": shared},
        {"url": "https://example.com/dupe-b", "text": shared},
    ]
    signatures = {p["url"]: minhash.signature(p["text"]) for p in pages}

    pairs, mode = analysis.find_near_duplicates(pages, signatures=signatures)

    assert mode == "minhash"
    assert any(
        {p["url_a"], p["url_b"]} == {"https://example.com/dupe-a", "https://example.com/dupe-b"}
        for p in pairs
    ), f"the planted duplicate pair was not reported: {pairs}"


def test_a_large_crawl_without_signatures_falls_back_to_exact():
    """Signatures are computed during the crawl, decided from the page cap. If
    a crawl somehow arrives here large but unsigned, the answer must still be
    correct -- slower beats wrong -- and the reported mode must say what
    actually ran rather than what was intended."""
    pages = _pages(analysis.EXACT_PATH_MAX_PAGES + 1)

    _, mode = analysis.find_near_duplicates(pages, signatures={})

    assert mode == "exact"


def test_both_paths_return_the_same_shape():
    """find_near_duplicates hands either path's output to the same caller."""
    shared = "identical content on both of these pages " * 40
    small = [{"url": "https://example.com/a", "text": shared},
             {"url": "https://example.com/b", "text": shared}]
    exact_pairs, _ = analysis.find_near_duplicates(small, signatures={})

    large = small + _pages(analysis.EXACT_PATH_MAX_PAGES)
    signatures = {p["url"]: minhash.signature(p["text"]) for p in large}
    minhash_pairs, _ = analysis.find_near_duplicates(large, signatures=signatures)

    assert set(exact_pairs[0]) == {"url_a", "url_b", "similarity"}
    assert set(minhash_pairs[0]) == {"url_a", "url_b", "similarity"}
