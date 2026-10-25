"""What counts as an alert-worthy rank change. Pure: no DB, no network."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

DEFAULTS = {"drop_threshold": 3, "top10_alerts": True, "gain_threshold": None}


@dataclass(frozen=True)
class Change:
    kind: str
    keyword_id: int
    rank_check_id: int
    phrase: str
    country: Optional[str]
    device: Optional[str]
    old_position: Optional[int]
    new_position: Optional[int]
    ranking_url: Optional[str]


def evaluate(previous, current, keyword, settings: Optional[dict]) -> List[Change]:
    """`previous` must already be the last non-skipped check. A skipped
    `current` says nothing about rank, so it never alerts."""
    if previous is None or current.status == "skipped":
        return []
    s = {**DEFAULTS, **(settings or {})}
    old, new = previous.position, current.position
    kinds = []
    if old is not None and new is None:
        kinds.append("lost")
    if old is not None and new is not None and new - old >= s["drop_threshold"]:
        kinds.append("drop")
    if s["top10_alerts"] and old is not None and old <= 10 and (new is None or new > 10):
        kinds.append("left_top10")
    if s["gain_threshold"] and old is not None and new is not None and old - new >= s["gain_threshold"]:
        kinds.append("gain")
    return [
        Change(kind=k, keyword_id=keyword.id, rank_check_id=current.id, phrase=keyword.phrase,
               country=keyword.country, device=keyword.device, old_position=old,
               new_position=new, ranking_url=current.ranking_url)
        for k in kinds
    ]
