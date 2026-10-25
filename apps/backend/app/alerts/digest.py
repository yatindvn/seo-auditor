"""One readable message per project run."""

from __future__ import annotations

from typing import List, Tuple

LABELS = {"drop": "dropped", "lost": "no longer ranks", "left_top10": "left the top 10", "gain": "improved"}


def _pos(value) -> str:
    return str(value) if value is not None else "not ranked"


def format_digest(domain: str, changes: List) -> Tuple[str, str]:
    keywords = {c.keyword_id for c in changes}
    subject = f"Rank changes for {domain}: {len(keywords)} keyword(s)"
    lines = []
    for c in sorted(changes, key=lambda c: (c.phrase, c.kind)):
        where = f"{c.country or 'US'}/{c.device or 'desktop'}"
        url = f" — {c.ranking_url}" if c.ranking_url else ""
        lines.append(f"- {c.phrase} [{where}]: {_pos(c.old_position)} → {_pos(c.new_position)} "
                     f"({LABELS.get(c.kind, c.kind)}){url}")
    return subject, "\n".join(lines)
