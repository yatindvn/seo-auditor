"""Search Console (Phase 5.5): status, performance, sync, and the audit join."""

from __future__ import annotations

from typing import Any, Dict, List, Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import asc, desc, func, select

from app.api.projects import _factory
from app.crawler.crawler import normalize_url
from app.db.models import Audit, AuditPage, GscDaily, GscInspection, GscPage, GscQuery, Project, as_utc
from app.gsc.provider import GscError, build_gsc_provider
from app.gsc.sync import sync_project

router = APIRouter()
Sort = Literal["clicks", "impressions", "ctr", "position"]


def kpis(rows) -> Dict[str, Any]:
    clicks = sum(r.clicks for r in rows)
    impressions = sum(r.impressions for r in rows)
    return {"clicks": round(clicks), "impressions": round(impressions),
            "ctr": round(clicks / impressions, 4) if impressions else None,
            "position": round(sum(r.position * r.impressions for r in rows) / impressions, 2) if impressions else None}


def _project(session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


@router.get("/gsc/sites")
def gsc_sites():
    provider = build_gsc_provider()
    if provider is None:
        return {"configured": False, "dry_run": False, "client_email": None, "sites": []}
    try:
        sites = provider.sites()
    except GscError as exc:
        raise HTTPException(status_code=502, detail=exc.message)
    return {"configured": True, "dry_run": provider.dry_run, "client_email": provider.client_email,
            "sites": [{"site_url": s.site_url, "permission": s.permission} for s in sites]}


@router.get("/projects/{project_id}/gsc")
def gsc_overview(project_id: int):
    provider = build_gsc_provider()
    with _factory()() as session:
        project = _project(session, project_id)
        rows = session.scalars(select(GscDaily).where(GscDaily.project_id == project_id)
                               .order_by(desc(GscDaily.date)).limit(90)).all()[::-1]
        latest, previous = rows[-28:], rows[-56:-28]
        return {
            "configured": provider is not None,
            "dry_run": bool((provider is not None and provider.dry_run) or any(r.dry_run for r in latest)),
            "client_email": provider.client_email if provider is not None else None,
            "property": project.gsc_property,
            "last_sync_at": as_utc(project.last_gsc_sync_at).isoformat() if project.last_gsc_sync_at else None,
            "kpis": kpis(latest) if latest else None,
            "previous_kpis": kpis(previous) if previous else None,
            "daily": [{"date": r.date.isoformat(), "clicks": r.clicks, "impressions": r.impressions,
                       "ctr": r.ctr, "position": r.position} for r in rows],
        }


def _listing(model, key_column, project_id: int, sort: str, limit: int, offset: int) -> Dict[str, Any]:
    with _factory()() as session:
        _project(session, project_id)
        column = getattr(model, sort)
        order = asc(column) if sort == "position" else desc(column)
        query = select(model).where(model.project_id == project_id).order_by(order, model.id)
        total = session.scalar(select(func.count()).select_from(model).where(model.project_id == project_id))
        items = session.scalars(query.offset(offset).limit(limit)).all()
        return {"total": total, "items": [{"key": getattr(r, key_column), "clicks": r.clicks, "impressions": r.impressions,
                                           "ctr": r.ctr, "position": r.position} for r in items]}


@router.get("/projects/{project_id}/gsc/pages")
def gsc_pages(project_id: int, sort: Sort = "clicks", limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    return _listing(GscPage, "url", project_id, sort, limit, offset)


@router.get("/projects/{project_id}/gsc/queries")
def gsc_queries(project_id: int, sort: Sort = "clicks", limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    return _listing(GscQuery, "query", project_id, sort, limit, offset)


@router.post("/projects/{project_id}/gsc/sync")
def gsc_sync(project_id: int):
    provider = build_gsc_provider()
    if provider is None:
        raise HTTPException(status_code=409, detail="Search Console is not configured (set GSC_SERVICE_ACCOUNT_FILE)")
    with _factory()() as session:
        _project(session, project_id)
    return sync_project(project_id, provider)


_INSPECTION_FIELDS = ("url", "verdict", "coverage_state", "indexing_state", "robots_state", "fetch_state",
                      "google_canonical", "user_canonical", "last_crawl", "error")


@router.get("/audits/{audit_id}/gsc")
def audit_gsc(audit_id: int):
    with _factory()() as session:
        audit = session.get(Audit, audit_id)
        if audit is None:
            raise HTTPException(status_code=404, detail="audit not found")
        summary = audit.summary_json or {}
        inspections = session.scalars(select(GscInspection).where(GscInspection.audit_id == audit_id)
                                      .order_by(GscInspection.id)).all()
        verdicts = {normalize_url(i.url): i.verdict for i in inspections}
        crawled = {normalize_url(u) for u in session.scalars(select(AuditPage.url).where(AuditPage.audit_id == audit_id))}
        gsc_rows = session.scalars(select(GscPage).where(GscPage.project_id == audit.project_id)).all()
        joined: List[Dict[str, Any]] = []
        not_crawled: List[Dict[str, Any]] = []
        for row in gsc_rows:
            key = normalize_url(row.url)
            if key in crawled:
                joined.append({"url": row.url, "clicks": row.clicks, "impressions": row.impressions, "ctr": row.ctr,
                               "position": row.position, "inspection_verdict": verdicts.get(key)})
            elif row.impressions > 0:
                not_crawled.append({"url": row.url, "clicks": row.clicks, "impressions": row.impressions})
        joined.sort(key=lambda r: (-r["clicks"], r["url"]))
        not_crawled.sort(key=lambda r: (-r["impressions"], r["url"]))
        return {"audit_id": audit_id, "status": summary.get("gsc_status") or "disabled",
                "property": summary.get("gsc_property"), "dry_run": bool(summary.get("gsc_dry_run")),
                "inspections": [{f: getattr(i, f) for f in _INSPECTION_FIELDS} for i in inspections],
                "pages": joined[:200], "not_crawled": not_crawled[:50]}
