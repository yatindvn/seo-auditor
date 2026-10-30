"""A topic's top results: SERP, our page analysis, bulk backlinks, a summary.
Live searches are reused for 7 days; dry-run ones are kept but never reused."""

from __future__ import annotations

import re
import statistics
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import desc, select

from app.backlinks.provider import get_backlink_provider
from app.content_explorer.pages import DryRunPages, fetch_results
from app.db.engine import get_session_factory
from app.db.models import ContentSearch, as_utc, utcnow
from app.providers import registry
from app.providers.serp import ProviderError, ProviderSkipped, SerpQuery

CACHE_DAYS = 7
RESULTS = 10
STOP_WORDS = {"the", "and", "for", "with", "you", "your", "are", "how", "what", "why", "when", "where", "who",
              "which", "can", "does", "from", "that", "this", "these", "those", "into", "about", "our", "all",
              "best", "top", "not", "but", "has", "have", "will", "more", "most", "its", "their", "them", "they"}


def normalize(topic: str, country: str, language: str) -> Tuple[str, str, str]:
    topic = " ".join((topic or "").lower().split())
    country, language = (country or "").strip().upper(), (language or "").strip().lower()
    if not 2 <= len(topic) <= 80:
        raise ValueError("topic must be 2-80 characters")
    if not re.fullmatch(r"[A-Z]{2}", country) or not re.fullmatch(r"[a-z]{2}", language):
        raise ValueError("country and language must be 2-letter codes")
    return topic, country, language


def _median(values: List[Optional[float]]) -> Optional[int]:
    present = [v for v in values if v is not None]
    return round(statistics.median(present)) if present else None


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    fetched = [r for r in rows if r.get("word_count") is not None]
    schema = Counter(t for r in fetched for t in set(r.get("schema_types") or []))
    terms: Counter = Counter()
    for r in fetched:
        words = {w for h in r.get("outline") or [] if h.get("level") == 2
                 for w in re.findall(r"[a-z]{3,}", (h.get("text") or "").lower()) if w not in STOP_WORDS}
        terms.update(words)
    return {"median_words": _median([r["word_count"] for r in fetched]),
            "median_referring_domains": _median([r.get("referring_domains") for r in rows]),
            "schema_counts": dict(sorted(schema.items(), key=lambda kv: (-kv[1], kv[0]))),
            "common_h2_terms": [{"term": t, "count": c} for t, c in sorted(terms.items(), key=lambda kv: (-kv[1], kv[0]))[:15]]}


def _json(row: ContentSearch, cached: bool) -> Dict[str, Any]:
    return {"id": row.id, "topic": row.topic, "country": row.country, "language": row.language,
            "created_at": as_utc(row.created_at).isoformat(), "cached": cached, "dry_run": row.dry_run,
            **(row.result_json or {})}


def explore(topic: str, country: str = "US", language: str = "en", refresh: bool = False, serp=None,
            backlinks=None, fetch=None, factory=None, now: Optional[datetime] = None) -> Dict[str, Any]:
    topic, country, language = normalize(topic, country, language)
    factory = factory or get_session_factory()
    now = now or utcnow()
    if not refresh:
        with factory() as session:
            hit = session.scalars(select(ContentSearch).where(
                ContentSearch.topic == topic, ContentSearch.country == country, ContentSearch.language == language,
                ContentSearch.dry_run.is_(False), ContentSearch.created_at >= now - timedelta(days=CACHE_DAYS),
                ContentSearch.created_at <= now,
            ).order_by(desc(ContentSearch.created_at), desc(ContentSearch.id)).limit(1)).first()
            if hit is not None:
                return _json(hit, cached=True)

    serp = serp if serp is not None else registry.get_serp_provider()
    try:
        items = serp.search(SerpQuery(topic, country, language, depth=RESULTS)).items[:RESULTS]
    except (ProviderSkipped, ProviderError):
        raise
    except Exception as exc:
        raise ProviderError(f"SERP request failed ({type(exc).__name__})") from exc
    live_serp = registry.is_live(serp)
    rows = fetch_results(items, fetch=fetch) if live_serp else DryRunPages().results(items, topic)

    backlinks = backlinks if backlinks is not None else get_backlink_provider()
    notes: List[str] = []
    metrics: Dict[str, Tuple[Optional[int], Optional[int]]] = {}
    try:
        metrics = backlinks.bulk_metrics([r["url"] for r in rows]) if rows else {}
    except ProviderSkipped as exc:
        notes.append(f"Backlinks skipped: {exc}")
    except Exception as exc:
        notes.append(f"Backlinks failed ({type(exc).__name__})")
    for r in rows:
        r["backlinks"], r["referring_domains"] = metrics.get(r["url"], (None, None))

    dry = not live_serp or bool(getattr(backlinks, "dry_run", False))
    with factory.begin() as session:
        row = ContentSearch(topic=topic, country=country, language=language, created_at=now, dry_run=dry,
                            result_json={"summary": summarize(rows), "results": rows, "notes": notes})
        session.add(row)
        session.flush()
        return _json(row, cached=False)


def get_search(search_id: int, factory=None) -> Optional[Dict[str, Any]]:
    with (factory or get_session_factory())() as session:
        row = session.get(ContentSearch, search_id)
        return _json(row, cached=True) if row else None


def recent(limit: int = 10, factory=None) -> List[Dict[str, Any]]:
    with (factory or get_session_factory())() as session:
        rows = session.scalars(select(ContentSearch).order_by(desc(ContentSearch.created_at), desc(ContentSearch.id))
                               .limit(limit)).all()
        return [{"id": r.id, "topic": r.topic, "country": r.country, "language": r.language,
                 "created_at": as_utc(r.created_at).isoformat(), "dry_run": r.dry_run} for r in rows]
