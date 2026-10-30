"""AI Visibility (Phase 7.1): prompts, brand terms, runs, results."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Query, Response
from sqlalchemy import delete, desc, func, select

from app.ai_visibility.detect import citation_domain, highlights
from app.ai_visibility.providers import provider_status
from app.ai_visibility.run import load_brands, run_project
from app.api.projects import _factory
from app.db.models import AiBrandTerm, AiPrompt, AiRun, AiVisibilityRun, Competitor, Project, as_utc

router = APIRouter()
MAX_PROMPTS = 25
MAX_TERMS = 10


def _project(session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


def rates(rows) -> Dict[str, Optional[float]]:
    ok = [r for r in rows if not r.error]
    positions = [r.position for r in ok if r.position]
    return {"mention_rate": round(sum(r.mentioned for r in ok) / len(ok), 3) if ok else None,
            "avg_position": round(sum(positions) / len(positions), 2) if positions else None,
            "cited_rate": round(sum(r.cited for r in ok) / len(ok), 3) if ok else None}


def _run_summary(run: AiRun, rows) -> Dict[str, Any]:
    providers = sorted({r.provider for r in rows})
    return {"run_id": run.id, "started_at": as_utc(run.started_at).isoformat(), "dry_run": run.dry_run,
            "calls": run.calls, "errors": run.errors, **rates(rows),
            "by_provider": {p: rates([r for r in rows if r.provider == p]) for p in providers}}


def _prompt_json(p: AiPrompt) -> Dict[str, Any]:
    return {"id": p.id, "text": p.text, "enabled": p.enabled}


@router.get("/projects/{project_id}/ai-visibility")
def overview(project_id: int):
    status = provider_status()
    with _factory()() as session:
        project = _project(session, project_id)
        runs = session.scalars(select(AiRun).where(AiRun.project_id == project_id, AiRun.finished_at.is_not(None))
                               .order_by(desc(AiRun.started_at), desc(AiRun.id)).limit(20)).all()
        rows_by_run = {run.id: session.scalars(select(AiVisibilityRun).where(AiVisibilityRun.run_id == run.id)).all()
                       for run in runs}
        latest = _run_summary(runs[0], rows_by_run[runs[0].id]) if runs else None
        previous = _run_summary(runs[1], rows_by_run[runs[1].id]) if len(runs) > 1 else None
        trend = [{"run_id": r.id, "started_at": as_utc(r.started_at).isoformat(),
                  "mention_rate": rates(rows_by_run[r.id])["mention_rate"],
                  "by_provider": {p: rates([x for x in rows_by_run[r.id] if x.provider == p])["mention_rate"]
                                  for p in sorted({x.provider for x in rows_by_run[r.id]})}} for r in reversed(runs)]
        share, cited = [], []
        if runs:
            ok = [r for r in rows_by_run[runs[0].id] if not r.error]
            brands = load_brands(session, project)
            share = sorted(({"owner": b.owner, "is_self": b.is_self,
                             "rate": round(sum(b.owner in (r.brands_json or []) for r in ok) / len(ok), 3) if ok else 0.0}
                            for b in brands), key=lambda s: (-s["rate"], not s["is_self"], s["owner"]))
            counts = Counter(d for r in ok for d in {citation_domain(c) for c in (r.citations_json or [])} if d)
            cited = [{"domain": d, "count": n, "is_self": d == project.domain or d.endswith("." + project.domain)}
                     for d, n in counts.most_common(10)]
        return {"providers": status, "dry_run": any(s["dry_run"] for s in status) or bool(latest and latest["dry_run"]),
                "schedule": project.ai_schedule,
                "last_run_at": as_utc(project.last_ai_run_at).isoformat() if project.last_ai_run_at else None,
                "latest": latest, "previous": previous, "trend": trend, "share_of_voice": share, "top_cited": cited}


@router.get("/projects/{project_id}/ai-visibility/prompts")
def list_prompts(project_id: int):
    with _factory()() as session:
        _project(session, project_id)
        return {"items": [_prompt_json(p) for p in session.scalars(
            select(AiPrompt).where(AiPrompt.project_id == project_id).order_by(AiPrompt.id))]}


def _clean_text(value: Any) -> str:
    text = (value or "").strip() if isinstance(value, str) else ""
    if not 1 <= len(text) <= 300:
        raise HTTPException(status_code=422, detail="prompt text must be 1-300 characters")
    return text


@router.post("/projects/{project_id}/ai-visibility/prompts", status_code=201)
def add_prompt(project_id: int, body: Dict[str, Any] = Body(...)):
    text = _clean_text(body.get("text"))
    with _factory().begin() as session:
        _project(session, project_id)
        count = session.scalar(select(func.count()).select_from(AiPrompt).where(AiPrompt.project_id == project_id))
        if count >= MAX_PROMPTS:
            raise HTTPException(status_code=409, detail=f"a project can have at most {MAX_PROMPTS} prompts")
        prompt = AiPrompt(project_id=project_id, text=text)
        session.add(prompt)
        session.flush()
        return _prompt_json(prompt)


@router.patch("/ai-prompts/{prompt_id}")
def update_prompt(prompt_id: int, body: Dict[str, Any] = Body(...)):
    with _factory().begin() as session:
        prompt = session.get(AiPrompt, prompt_id)
        if prompt is None:
            raise HTTPException(status_code=404, detail="prompt not found")
        if "text" in body:
            prompt.text = _clean_text(body["text"])
        if "enabled" in body:
            prompt.enabled = bool(body["enabled"])
        session.flush()
        return _prompt_json(prompt)


@router.delete("/ai-prompts/{prompt_id}", status_code=204)
def delete_prompt(prompt_id: int):
    with _factory().begin() as session:
        prompt = session.get(AiPrompt, prompt_id)
        if prompt is None:
            raise HTTPException(status_code=404, detail="prompt not found")
        session.delete(prompt)
    return Response(status_code=204)


def _brands_json(session, project: Project) -> Dict[str, Any]:
    terms: Dict[str, List[str]] = {}
    for t in session.scalars(select(AiBrandTerm).where(AiBrandTerm.project_id == project.id).order_by(AiBrandTerm.id)):
        terms.setdefault(t.owner, []).append(t.term)
    competitors = session.scalars(select(Competitor.domain).where(Competitor.project_id == project.id).order_by(Competitor.id)).all()
    return {"self": {"domain": project.domain, "terms": terms.get(project.domain, [])},
            "competitors": [{"domain": d, "terms": terms.get(d, [])} for d in competitors]}


def _clean_terms(values: Any) -> List[str]:
    if not isinstance(values, list):
        raise HTTPException(status_code=422, detail="terms must be a list")
    out: List[str] = []
    for value in values:
        term = (value or "").strip() if isinstance(value, str) else ""
        if not 1 <= len(term) <= 100:
            raise HTTPException(status_code=422, detail="each term must be 1-100 characters")
        if term.lower() not in (t.lower() for t in out):
            out.append(term)
    if len(out) > MAX_TERMS:
        raise HTTPException(status_code=422, detail=f"at most {MAX_TERMS} terms per brand")
    return out


@router.get("/projects/{project_id}/ai-visibility/brands")
def get_brands(project_id: int):
    with _factory()() as session:
        return _brands_json(session, _project(session, project_id))


@router.put("/projects/{project_id}/ai-visibility/brands")
def put_brands(project_id: int, body: Dict[str, Any] = Body(...)):
    with _factory().begin() as session:
        project = _project(session, project_id)
        competitors = set(session.scalars(select(Competitor.domain).where(Competitor.project_id == project_id)))
        updates: Dict[str, List[str]] = {}
        if "self" in body:
            updates[project.domain] = _clean_terms(body["self"])
        for domain, values in (body.get("competitors") or {}).items():
            if domain not in competitors:
                raise HTTPException(status_code=400, detail=f"{domain} is not a competitor of this project")
            updates[domain] = _clean_terms(values)
        for owner, terms in updates.items():
            session.execute(delete(AiBrandTerm).where(AiBrandTerm.project_id == project_id, AiBrandTerm.owner == owner))
            session.add_all(AiBrandTerm(project_id=project_id, owner=owner, term=t) for t in terms)
        session.flush()
        return _brands_json(session, project)


@router.post("/projects/{project_id}/ai-visibility/run")
def run_now(project_id: int):
    with _factory()() as session:
        _project(session, project_id)
    return run_project(project_id)


@router.get("/projects/{project_id}/ai-visibility/answers")
def answers(project_id: int, run_id: Optional[int] = None, provider: Optional[str] = None,
            prompt_id: Optional[int] = None, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    with _factory()() as session:
        project = _project(session, project_id)
        if run_id is None:
            run_id = session.scalar(select(AiRun.id).where(AiRun.project_id == project_id, AiRun.finished_at.is_not(None))
                                    .order_by(desc(AiRun.started_at), desc(AiRun.id)).limit(1))
        if run_id is None:
            return {"run_id": None, "total": 0, "items": []}
        query = select(AiVisibilityRun).where(AiVisibilityRun.run_id == run_id, AiVisibilityRun.project_id == project_id)
        if provider:
            query = query.where(AiVisibilityRun.provider == provider)
        if prompt_id is not None:
            query = query.where(AiVisibilityRun.prompt_id == prompt_id)
        rows = session.scalars(query.order_by(AiVisibilityRun.prompt_id, AiVisibilityRun.provider, AiVisibilityRun.id)).all()
        brands = load_brands(session, project)
        items = [{"id": r.id, "prompt": r.prompt, "provider": r.provider, "model": r.model, "mentioned": r.mentioned,
                  "position": r.position, "brands": r.brands_json or [], "cited": r.cited,
                  "citations": r.citations_json or [], "error": r.error, "answer": r.answer,
                  "highlights": highlights(r.answer, brands) if not r.error else []}
                 for r in rows[offset:offset + limit]]
        return {"run_id": run_id, "total": len(rows), "items": items}
