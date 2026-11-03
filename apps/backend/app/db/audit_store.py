"""Copy a finished audit from its session file into the central database."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import insert, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import AccessibilityScan, Audit, GscInspection, AuditIssue, AuditPage, Keyword, RankCheck, RenderedPage, WebVital, utcnow
from app.db.projects import get_or_create_project
from app.services.summary_fields import SUMMARY_FIELDS

BATCH_SIZE = 500
RANK_PROVIDER = "google_cse"


def _summary(result: Dict[str, Any]) -> Dict[str, Any]:
    return {field: result[field] for field in SUMMARY_FIELDS if field in result}


def _parse_time(value: Optional[str]) -> datetime:
    try:
        return datetime.fromisoformat(value) if value else utcnow()
    except ValueError:
        return utcnow()


def _keyword(session: Session, project_id: int, phrase: str, target_url: str) -> Keyword:
    # Looked up explicitly: country and device are NULL here, and SQL unique
    # constraints treat NULLs as distinct, so the constraint alone would not
    # stop a second "espresso" row.
    keyword = session.scalar(select(Keyword).where(
        Keyword.project_id == project_id, Keyword.phrase == phrase,
        Keyword.country.is_(None), Keyword.device.is_(None),
    ))
    if keyword is None:
        keyword = Keyword(project_id=project_id, phrase=phrase, target_url=target_url)
        session.add(keyword)
        session.flush()
    return keyword


def _record_rankings(session: Session, project_id: int, audit_id: int, pages: List[Dict]) -> None:
    for page in pages:
        rankings = ((page.get("keyword_analysis") or {}).get("rankings")) or []
        for ranking in rankings:
            keyword = _keyword(session, project_id, ranking["keyword"], page.get("url"))
            position = ranking.get("position")
            top = ranking.get("top_urls") or []
            session.add(RankCheck(
                keyword_id=keyword.id, audit_id=audit_id,
                checked_at=_parse_time(ranking.get("checked_at")),
                provider=RANK_PROVIDER, status=ranking.get("status") or "skipped",
                position=position,
                ranking_url=top[position - 1] if position and len(top) >= position else None,
                note=ranking.get("note"),
            ))


_VITALS_COLUMNS = ("url", "strategy", "source", "data_kind", "rating", "performance_score",
                   "lcp_ms", "inp_ms", "cls", "fcp_ms", "ttfb_ms", "tbt_ms", "error")


def _record_vitals(session: Session, audit_id: int, rows: List[Dict[str, Any]]) -> None:
    if rows:
        now = utcnow()
        session.execute(insert(WebVital), [
            {**{c: row.get(c) for c in _VITALS_COLUMNS}, "audit_id": audit_id, "measured_at": now}
            for row in rows
        ])


def _record_rendering(session: Session, audit_id: int, rows: List[Dict[str, Any]]) -> None:
    if rows:
        session.execute(insert(RenderedPage), [{
            "audit_id": audit_id, "url": r["url"], "status": r.get("status", "rendered"),
            "error": r.get("error"), "render_ms": r.get("render_ms"),
            "raw_word_count": r.get("raw_word_count"), "rendered_word_count": r.get("rendered_word_count"),
            "changes_json": r.get("changes") or {}, "js_only_links_json": r.get("js_only_links") or [],
            "js_only_links_count": r.get("js_only_links_count") or 0,
        } for r in rows])


def _record_accessibility(session: Session, audit_id: int, rows: List[Dict[str, Any]]) -> None:
    if rows:
        session.execute(insert(AccessibilityScan), [{
            "audit_id": audit_id, "url": r["url"], "status": r.get("status", "scanned"),
            "error": r.get("error"), "score": r.get("score"),
            **{k: (r.get("counts") or {}).get(k, 0) for k in ("critical", "serious", "moderate", "minor")},
            "violations_json": r.get("violations") or [],
        } for r in rows])


_GSC_COLUMNS = ("url", "verdict", "coverage_state", "indexing_state", "robots_state", "fetch_state",
                "google_canonical", "user_canonical", "last_crawl", "error")


def _record_gsc(session: Session, audit_id: int, rows: List[Dict[str, Any]], dry_run: bool) -> None:
    if rows:
        session.execute(insert(GscInspection), [
            {**{c: r.get(c) for c in _GSC_COLUMNS}, "audit_id": audit_id, "dry_run": dry_run} for r in rows])


def record_audit(
    factory: sessionmaker,
    session_db,
    result: Dict[str, Any],
    *,
    session_id: str,
    start_url: str,
    trigger: str = "manual",
    started_at: Optional[datetime] = None,
) -> Tuple[int, int]:
    """Store one audit; return (audit_id, project_id). One transaction: a
    failure stores nothing. Raises -- the caller decides what failure means."""
    with factory.begin() as session:
        project = get_or_create_project(session, start_url)
        health = ((result.get("executive_summary") or {}).get("health_score") or {}).get("score")
        audit = Audit(
            project_id=project.id, session_id=session_id, start_url=start_url,
            status="partial" if result.get("partial") else "completed",
            trigger=trigger, started_at=started_at or utcnow(), finished_at=utcnow(),
            page_count=0, health_score=health, summary_json=_summary(result),
        )
        session.add(audit)
        session.flush()

        page_count = 0
        for batch in session_db.iter_pages(BATCH_SIZE):
            session.execute(insert(AuditPage), [{**row, "audit_id": audit.id} for row in batch])
            # Rows that turned out to be another page (a copy, or a redirect onto
            # one already claimed) are stored for the dashboard but were never
            # analysed: they are not pages of this audit.
            page_count += sum(1 for row in batch if not (row.get("duplicate_of") or row.get("alias_of")))
        for batch in session_db.iter_issues(BATCH_SIZE):
            session.execute(insert(AuditIssue), [{**row, "audit_id": audit.id} for row in batch])

        audit.page_count = page_count
        _record_rankings(session, project.id, audit.id, result.get("pages") or [])
        _record_vitals(session, audit.id, result.get("web_vitals") or [])
        _record_rendering(session, audit.id, result.get("rendering") or [])
        _record_accessibility(session, audit.id, result.get("accessibility") or [])
        _record_gsc(session, audit.id, result.get("gsc_inspections") or [], bool(result.get("gsc_dry_run")))
        return audit.id, project.id
