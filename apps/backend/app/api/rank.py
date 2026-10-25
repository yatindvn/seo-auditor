"""Rank tracking over HTTP: keywords, competitors, history, manual runs."""

from __future__ import annotations

from datetime import timedelta
from typing import List, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.projects import _factory
from app.db.models import Competitor, Keyword, Project, RankCheck, as_utc, utcnow
from app.db.projects import project_domain
from app.providers import registry
from app.providers.dry_run import DryRunProvider
from app.providers.serp import ProviderSkipped, SerpQuery
from app.rank import tracker

router = APIRouter()


class KeywordIn(BaseModel):
    phrase: str = Field(min_length=1, max_length=255)
    country: str = Field("US", min_length=2, max_length=2)
    language: str = Field("en", min_length=2, max_length=8)
    device: Literal["desktop", "mobile"] = "desktop"


class KeywordsIn(BaseModel):
    keywords: List[KeywordIn] = Field(min_length=1, max_length=500)


class KeywordPatch(BaseModel):
    enabled: bool


class CompetitorIn(BaseModel):
    domain: str


def _project_or_404(session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="no such project")
    return project


def _check_json(check: Optional[RankCheck]):
    if check is None:
        return None
    return {"position": check.position, "ranking_url": check.ranking_url, "status": check.status,
            "checked_at": as_utc(check.checked_at).isoformat(), "note": check.note,
            "competitor_positions": check.competitor_positions_json or {}}


@router.post("/projects/{project_id}/keywords")
def add_keywords(project_id: int, body: KeywordsIn):
    created = skipped = 0
    with _factory().begin() as session:
        project = _project_or_404(session, project_id)
        for item in body.keywords:
            phrase = " ".join(item.phrase.lower().split())
            country, device = item.country.upper(), item.device
            exists = session.scalar(select(Keyword.id).where(
                Keyword.project_id == project_id, Keyword.phrase == phrase,
                Keyword.country == country, Keyword.device == device))
            if exists:
                skipped += 1
                continue
            session.add(Keyword(project_id=project_id, phrase=phrase, country=country,
                                device=device, language=item.language.lower()))
            session.flush()
            created += 1
        if created and project.rank_schedule is None:
            project.rank_schedule = "daily"
    return {"created": created, "skipped": skipped}


@router.get("/projects/{project_id}/keywords")
def list_keywords(project_id: int):
    with _factory()() as session:
        _project_or_404(session, project_id)
        items = []
        for kw in session.scalars(select(Keyword).where(Keyword.project_id == project_id)
                                  .order_by(Keyword.phrase, Keyword.id)):
            latest = session.scalar(select(RankCheck).where(RankCheck.keyword_id == kw.id)
                                    .order_by(RankCheck.id.desc()).limit(1))
            previous = tracker.previous_real_check(session, kw.id, latest.id) if latest else None
            change = None
            if latest and previous and latest.position is not None and previous.position is not None:
                change = previous.position - latest.position     # positive = improved
            items.append({"id": kw.id, "phrase": kw.phrase, "country": kw.country or "US",
                          "device": kw.device or "desktop", "language": kw.language,
                          "enabled": kw.enabled, "latest": _check_json(latest), "change": change})
        return {"items": items}


@router.patch("/keywords/{keyword_id}")
def update_keyword(keyword_id: int, body: KeywordPatch):
    with _factory().begin() as session:
        kw = session.get(Keyword, keyword_id)
        if kw is None:
            raise HTTPException(status_code=404, detail="no such keyword")
        kw.enabled = body.enabled
        return {"id": kw.id, "enabled": kw.enabled}


@router.delete("/keywords/{keyword_id}", status_code=204)
def delete_keyword(keyword_id: int):
    with _factory().begin() as session:
        kw = session.get(Keyword, keyword_id)
        if kw is None:
            raise HTTPException(status_code=404, detail="no such keyword")
        session.query(RankCheck).filter(RankCheck.keyword_id == keyword_id).delete()
        session.delete(kw)
    return Response(status_code=204)


@router.get("/keywords/{keyword_id}/history")
def keyword_history(keyword_id: int, days: int = Query(90, ge=1, le=730)):
    with _factory()() as session:
        if session.get(Keyword, keyword_id) is None:
            raise HTTPException(status_code=404, detail="no such keyword")
        since = utcnow() - timedelta(days=days)
        checks = session.scalars(select(RankCheck).where(RankCheck.keyword_id == keyword_id,
                                                         RankCheck.checked_at >= since)
                                 .order_by(RankCheck.checked_at, RankCheck.id)).all()
        return {"items": [_check_json(c) for c in checks]}


@router.get("/projects/{project_id}/competitors")
def list_competitors(project_id: int):
    with _factory()() as session:
        _project_or_404(session, project_id)
        rows = session.scalars(select(Competitor).where(Competitor.project_id == project_id)
                               .order_by(Competitor.domain)).all()
        return {"items": [{"id": c.id, "domain": c.domain} for c in rows]}


@router.post("/projects/{project_id}/competitors", status_code=201)
def add_competitor(project_id: int, body: CompetitorIn):
    domain = project_domain(body.domain)
    try:
        with _factory().begin() as session:
            _project_or_404(session, project_id)
            competitor = Competitor(project_id=project_id, domain=domain)
            session.add(competitor)
            session.flush()
            return {"id": competitor.id, "domain": competitor.domain}
    except IntegrityError:
        raise HTTPException(status_code=409, detail=f"{domain} is already a competitor")


@router.delete("/projects/{project_id}/competitors/{competitor_id}", status_code=204)
def delete_competitor(project_id: int, competitor_id: int):
    with _factory().begin() as session:
        competitor = session.get(Competitor, competitor_id)
        if competitor is None or competitor.project_id != project_id:
            raise HTTPException(status_code=404, detail="no such competitor")
        session.delete(competitor)
    return Response(status_code=204)


@router.post("/projects/{project_id}/rank-checks/run")
def run_rank_checks(project_id: int, background_tasks: BackgroundTasks, dry_run: bool = True):
    if dry_run:
        # A preview: made-up positions from the dry-run provider. Never stored,
        # never alerted on.
        provider = DryRunProvider()
        with _factory()() as session:
            project = _project_or_404(session, project_id)
            competitors = list(session.scalars(select(Competitor.domain)
                                               .where(Competitor.project_id == project_id)))
            results = []
            for kw in session.scalars(select(Keyword).where(Keyword.project_id == project_id,
                                                            Keyword.enabled.is_(True)).limit(50)):
                serp = provider.search(SerpQuery(kw.phrase, country=kw.country or "US",
                                                 device=kw.device or "desktop"))
                position, url = tracker.position_for(serp.items, project.domain)
                results.append({"phrase": kw.phrase, "position": position, "ranking_url": url,
                                "competitor_positions": {d: tracker.position_for(serp.items, d)[0]
                                                         for d in competitors}})
        return {"dry_run": True, "results": results}

    try:
        provider = registry.get_serp_provider()
    except ProviderSkipped as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if not registry.is_live(provider):
        raise HTTPException(status_code=409,
                            detail="no live SERP provider: set SERP_PROVIDER (and SERP_DRY_RUN=false for paid providers)")
    with _factory()() as session:
        _project_or_404(session, project_id)
    background_tasks.add_task(tracker.run_project, project_id, provider=provider)
    return {"dry_run": False, "status": "accepted"}
