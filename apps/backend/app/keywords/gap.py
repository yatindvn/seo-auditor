"""Content gap: keywords where a competitor ranks in the top 20 and I don't
rank in the top 100, ordered by opportunity (volume weighted by ease)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.db.projects import project_domain
from app.providers import registry

MAX_COMPETITORS = 5
COMPETITOR_MAX_POSITION = 20
MINE_MAX_POSITION = 100
UNKNOWN_DIFFICULTY = 50


def opportunity(volume: Optional[int], difficulty: Optional[int]) -> float:
    kd = UNKNOWN_DIFFICULTY if difficulty is None else difficulty
    return round((volume or 0) * (100 - kd) / 100, 1)


@dataclass
class GapResult:
    my_domain: str
    competitors: List[str]
    dry_run: bool
    rows: List[Dict] = field(default_factory=list)
    total_gaps: int = 0


def content_gap(my_domain: str, competitors: List[str], country: str = "US", language: str = "en",
                limit: int = 500, data=None) -> GapResult:
    mine_domain = project_domain(my_domain)
    rivals: List[str] = []
    for c in competitors:
        d = project_domain(c)
        if d and d != mine_domain and d not in rivals:
            rivals.append(d)
    if not 1 <= len(rivals) <= MAX_COMPETITORS:
        raise ValueError(f"need 1 to {MAX_COMPETITORS} competitors other than {mine_domain}")

    data = data or registry.get_keyword_provider()
    country, language = country.upper(), language.lower()
    mine = {rk.keyword: rk.position for rk in data.ranked_keywords(mine_domain, country, language, limit)}

    rows: Dict[str, Dict] = {}
    for rival in rivals:
        for rk in data.ranked_keywords(rival, country, language, limit):
            if rk.position > COMPETITOR_MAX_POSITION:
                continue
            if mine.get(rk.keyword, MINE_MAX_POSITION + 1) <= MINE_MAX_POSITION:
                continue
            row = rows.setdefault(rk.keyword, {"keyword": rk.keyword, "search_volume": rk.search_volume,
                                               "difficulty": rk.difficulty, "competitors": {}})
            if row["search_volume"] is None:
                row["search_volume"] = rk.search_volume
            if row["difficulty"] is None:
                row["difficulty"] = rk.difficulty
            row["competitors"][rival] = {"position": rk.position, "url": rk.url}

    finished = []
    for row in rows.values():
        row["best_competitor_position"] = min(c["position"] for c in row["competitors"].values())
        row["opportunity"] = opportunity(row["search_volume"], row["difficulty"])
        finished.append(row)
    finished.sort(key=lambda r: (-r["opportunity"], -(r["search_volume"] or 0), r["keyword"]))
    return GapResult(my_domain=mine_domain, competitors=rivals, dry_run=not registry.is_live(data),
                     rows=finished, total_gaps=len(finished))
