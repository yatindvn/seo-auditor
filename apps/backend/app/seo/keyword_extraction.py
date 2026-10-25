"""
keyword_extraction.py — On-page keyword extraction via weighted n-gram frequency.

Pure logic: no network calls, no new dependencies. Supersedes the old,
uncalled `keyword_density()` helper in checks.py — that function is left in
place (removing it is a separate cleanup) but this module is what the audit
pipeline actually uses for keyword extraction.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List

from app.auditor.checks import STOP_WORDS

FIELD_WEIGHTS = {
    "title": 3.0,
    "h1": 2.5,
    "meta_description": 2.0,
    "headings": 1.5,
    "body": 1.0,
}


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z']+", text.lower())


def _is_content_word(token: str) -> bool:
    return token not in STOP_WORDS and len(token) > 2


def _phrases_from_text(text: str) -> List[str]:
    """Every 1-, 2- and 3-gram made only of content words.

    Such an n-gram always lies inside one run of consecutive content words, so
    each token is classified once and n-grams are taken run by run -- instead of
    re-testing every token for each of the three n-gram sizes it appears in.
    """
    phrases: List[str] = []
    run: List[str] = []
    for token in _tokenize(text) + [""]:  # sentinel flushes the last run
        if token and _is_content_word(token):
            run.append(token)
            continue
        for n in (1, 2, 3):
            for i in range(len(run) - n + 1):
                phrases.append(" ".join(run[i:i + n]))
        run = []
    return phrases


def extract_keywords(page_meta: Dict, content_stats: Dict, top_n: int = 8) -> List[Dict]:
    field_text = {
        "title": page_meta.get("title") or "",
        "h1": page_meta.get("h1") or "",
        "meta_description": page_meta.get("meta_description") or "",
        "headings": " ".join(h.get("text", "") for h in (page_meta.get("heading_hierarchy") or [])),
        "body": content_stats.get("text") or "",
    }

    scores: Dict[str, float] = {}
    found_in: Dict[str, List[str]] = {}

    for field, text in field_text.items():
        if not text:
            continue
        weight = FIELD_WEIGHTS[field]
        for phrase, count in Counter(_phrases_from_text(text)).items():
            scores[phrase] = scores.get(phrase, 0.0) + count * weight
            found_in.setdefault(phrase, [])
            if field not in found_in[phrase]:
                found_in[phrase].append(field)

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return [
        {"phrase": phrase, "score": round(score, 2), "found_in": found_in[phrase]}
        for phrase, score in ranked[:top_n]
    ]
