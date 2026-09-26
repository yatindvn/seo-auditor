"""MinHash signatures with LSH banding.

Each page reduces to SIGNATURE_LENGTH 32-bit minima over its word shingles: 512
bytes, against roughly 50 KB for a full shingle set. Two pages become candidates
when any of BANDS consecutive slices of their signatures match exactly, and the
estimated Jaccard is then the fraction of signature positions that agree.

Approximate by construction. At 128 permutations the standard error of the
estimate is about 1/sqrt(128), near 0.09 in the worst case and smaller near the
ends of the range, so a pair sitting on the threshold may fall either side of
it. That is why app/analysis/analysis.py keeps the exact path for crawls of 500
pages or fewer and uses this only above that, and why the chosen path is
reported to the client.
"""

from __future__ import annotations

import hashlib
from array import array
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

SIGNATURE_LENGTH = 128
BANDS = 16
ROWS_PER_BAND = SIGNATURE_LENGTH // BANDS  # 8
SHINGLE_SIZE = 5
MASK32 = 0xFFFFFFFF


def _permutations() -> List[Tuple[int, int]]:
    """Coefficients for h_i(x) = (a_i * x + b_i) mod 2**32.

    Derived from a fixed seed, not from `hash()`: signatures are compared across
    worker processes and across runs, and Python randomises `hash()` per process,
    so a `hash()`-derived signature would silently differ between the process
    that wrote it and the one that reads it.
    """
    # One digest per index: blake2b caps its output at 64 bytes, well short of
    # the 8 x SIGNATURE_LENGTH needed for a single draw.
    coefficients = []
    for index in range(SIGNATURE_LENGTH):
        chunk = hashlib.blake2b(
            b"seo-auditor-minhash-v1" + index.to_bytes(4, "big"), digest_size=8
        ).digest()
        # Odd multiplier, so multiplication mod 2**32 stays a bijection.
        a = int.from_bytes(chunk[:4], "big") | 1
        b = int.from_bytes(chunk[4:], "big")
        coefficients.append((a, b))
    return coefficients


_PERMUTATIONS = _permutations()
# Held as numpy arrays so every permutation is applied to every shingle in one
# vectorised step. The scalar Python equivalent is SIGNATURE_LENGTH multiply-add
# -compares per shingle: measured at 50 ms for a 2000-word page against 5 ms
# here, which alone would have consumed more than half the per-page CPU budget.
# The two produce byte-identical signatures; this is speed, not a different
# algorithm.
_A = np.array([a for a, _ in _PERMUTATIONS], dtype=np.uint64)
_B = np.array([b for _, b in _PERMUTATIONS], dtype=np.uint64)
_MASK = np.uint64(MASK32)


def _shingle_hashes(text: str, shingle_size: int) -> List[int]:
    words = text.lower().split()
    if not words:
        return []
    limit = max(len(words) - shingle_size + 1, 1)
    seen = set()
    for start in range(limit):
        shingle = " ".join(words[start:start + shingle_size])
        seen.add(int.from_bytes(
            hashlib.blake2b(shingle.encode("utf-8"), digest_size=4).digest(), "big"
        ))
    return list(seen)


def signature(text: str, shingle_size: int = SHINGLE_SIZE) -> Optional[bytes]:
    """Return a 512-byte signature, or None when there is no text to sign."""
    hashes = _shingle_hashes(text or "", shingle_size)
    if not hashes:
        return None

    values = np.fromiter(hashes, dtype=np.uint64, count=len(hashes))
    # One (shingles x permutations) pass: a*x+b mod 2**32 for every pair, then
    # the minimum down each permutation. a < 2**32 and x < 2**32, so the product
    # stays inside uint64 and the mask does the modulo.
    minima = ((_A * values[:, None] + _B) & _MASK).min(axis=0)
    return minima.astype(np.uint32).tobytes()


def estimated_jaccard(left: bytes, right: bytes) -> float:
    a, b = array("I"), array("I")
    a.frombytes(left)
    b.frombytes(right)
    matches = sum(1 for x, y in zip(a, b) if x == y)
    return matches / SIGNATURE_LENGTH


def candidate_pairs(signatures: Dict[str, Optional[bytes]]) -> Set[Tuple[str, str]]:
    """Pairs sharing at least one band, which is what makes this sub-quadratic:
    most pairs are never compared at all."""
    buckets: Dict[Tuple[int, bytes], List[str]] = {}
    for url, raw in signatures.items():
        if not raw:
            continue
        for band in range(BANDS):
            start = band * ROWS_PER_BAND * 4  # 4 bytes per 32-bit value
            key = (band, raw[start:start + ROWS_PER_BAND * 4])
            buckets.setdefault(key, []).append(url)

    pairs: Set[Tuple[str, str]] = set()
    for members in buckets.values():
        if len(members) < 2:
            continue
        for position, first in enumerate(members):
            for second in members[position + 1:]:
                pairs.add((first, second) if first < second else (second, first))
    return pairs


def near_duplicates(
    signatures: Dict[str, Optional[bytes]], threshold: float = 0.85
) -> List[Dict]:
    """Same output shape as analysis.near_duplicate_content, so either path can
    be returned to the same caller."""
    results = []
    for url_a, url_b in sorted(candidate_pairs(signatures)):
        similarity = estimated_jaccard(signatures[url_a], signatures[url_b])
        if similarity >= threshold:
            results.append({
                "url_a": url_a, "url_b": url_b, "similarity": round(similarity, 3),
            })
    return results
