"""Backlinks (Phase 6): profile, growth, lists, refresh, and the link gap."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Body, HTTPException, Query
from sqlalchemy import desc, func, select

from app.api.projects import _factory
from app.backlinks.gap import GapError, link_gap
from app.backlinks.provider import get_backlink_provider
from app.backlinks.snapshot import refresh_project
from app.crawler.crawler import normalize_url
from app.db.models import Audit, AuditPage, BacklinkLink, BacklinkRefDomain, BacklinkSnapshot, Project, as_utc
from app.providers.serp import ProviderError, ProviderSkipped

router = APIRouter()


def _project(session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


def _totals(s: BacklinkSnapshot) -> Dict[str, Any]:
    return {"taken_at": as_utc(s.taken_at).isoformat(), "authority": s.authority, "backlinks": s.backlinks,
            "referring_domains": s.referring_domains, "broken_backlinks": s.broken_backlinks, "dry_run": s.dry_run}


def _latest_snapshot_id(session, project_id: int) -> Optional[int]:
    return session.scalar(select(BacklinkSnapshot.id).where(
        BacklinkSnapshot.project_id == project_id, BacklinkSnapshot.source == "snapshot")
        .order_by(desc(BacklinkSnapshot.taken_at), desc(BacklinkSnapshot.id)).limit(1))


@router.get("/projects/{project_id}/backlinks")
def overview(project_id: int):
    provider = get_backlink_provider()
    with _factory()() as session:
        project = _project(session, project_id)
        snaps = session.scalars(select(BacklinkSnapshot).where(
            BacklinkSnapshot.project_id == project_id, BacklinkSnapshot.source == "snapshot")
            .order_by(desc(BacklinkSnapshot.taken_at), desc(BacklinkSnapshot.id)).limit(2)).all()
        rows = session.scalars(select(BacklinkSnapshot).where(BacklinkSnapshot.project_id == project_id)).all()
        history = sorted(({"date": (r.period or as_utc(r.taken_at).date()).isoformat(), "authority": r.authority,
                           "backlinks": r.backlinks, "referring_domains": r.referring_domains,
                           "source": r.source} for r in rows), key=lambda h: (h["date"], h["source"] != "history"))
        return {"dry_run_provider": provider.dry_run, "schedule": project.backlink_schedule,
                "last_refresh_at": as_utc(project.last_backlink_refresh_at).isoformat() if project.last_backlink_refresh_at else None,
                "latest": _totals(snaps[0]) if snaps else None,
                "previous": _totals(snaps[1]) if len(snaps) > 1 else None,
                "history": history}


@router.get("/projects/{project_id}/backlinks/referring-domains")
def referring_domains(project_id: int, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    with _factory()() as session:
        _project(session, project_id)
        snap_id = _latest_snapshot_id(session, project_id)
        if snap_id is None:
            return {"total": 0, "items": []}
        where = BacklinkRefDomain.snapshot_id == snap_id
        total = session.scalar(select(func.count()).select_from(BacklinkRefDomain).where(where))
        items = session.scalars(select(BacklinkRefDomain).where(where)
                                .order_by(desc(BacklinkRefDomain.rank), BacklinkRefDomain.id).offset(offset).limit(limit)).all()
        return {"total": total, "items": [{"domain": d.domain, "rank": d.rank, "backlinks": d.backlinks,
                                           "first_seen": d.first_seen} for d in items]}


@router.get("/projects/{project_id}/backlinks/links")
def links(project_id: int, kind: Literal["new", "lost", "broken"], limit: int = Query(50, ge=1, le=200),
          offset: int = Query(0, ge=0)):
    with _factory()() as session:
        _project(session, project_id)
        snap_id = _latest_snapshot_id(session, project_id)
        if snap_id is None:
            return {"total": 0, "items": []}
        where = (BacklinkLink.snapshot_id == snap_id) & (BacklinkLink.kind == kind)
        total = session.scalar(select(func.count()).select_from(BacklinkLink).where(where))
        rows = session.scalars(select(BacklinkLink).where(where)
                               .order_by(desc(BacklinkLink.domain_from_rank), BacklinkLink.id).offset(offset).limit(limit)).all()
        crawled: Dict[str, int] = {}
        if kind == "broken":
            audit_id = session.scalar(select(Audit.id).where(Audit.project_id == project_id)
                                      .order_by(desc(Audit.finished_at), desc(Audit.id)).limit(1))
            if audit_id is not None:
                crawled = {normalize_url(u): s for u, s in session.execute(
                    select(AuditPage.url, AuditPage.status).where(AuditPage.audit_id == audit_id)) if s is not None}
        items: List[Dict[str, Any]] = []
        for l in rows:
            item = {"url_from": l.url_from, "url_to": l.url_to, "anchor": l.anchor, "domain_from_rank": l.domain_from_rank,
                    "dofollow": l.dofollow, "first_seen": l.first_seen, "last_seen": l.last_seen,
                    "target_status": l.target_status}
            if kind == "broken":
                item["crawled_status"] = crawled.get(normalize_url(l.url_to))
            items.append(item)
        return {"total": total, "items": items}


@router.post("/projects/{project_id}/backlinks/refresh")
def refresh(project_id: int):
    with _factory()() as session:
        _project(session, project_id)
    return refresh_project(project_id, get_backlink_provider())


@router.post("/projects/{project_id}/backlinks/gap")
def gap(project_id: int, body: Dict[str, Any] = Body(default={})):
    with _factory()() as session:
        _project(session, project_id)
    competitors = body.get("competitors") if isinstance(body, dict) else None
    try:
        return link_gap(project_id, competitors, get_backlink_provider())
    except GapError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ProviderSkipped as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
