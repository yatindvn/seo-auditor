"""Asking every enabled prompt of every model, analysing and storing each answer."""

from __future__ import annotations

import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from sqlalchemy import insert, select

from app.ai_visibility.detect import Brand, analyze
from app.ai_visibility.providers import Answer, configured_providers
from app.db.engine import get_session_factory
from app.db.models import AiBrandTerm, AiPrompt, AiRun, AiVisibilityRun, Competitor, Project, utcnow

logger = logging.getLogger(__name__)
MAX_ANSWER = 8000
WORKERS = 3


def load_brands(session, project: Project) -> List[Brand]:
    by_owner: Dict[str, List[str]] = defaultdict(list)
    for term in session.scalars(select(AiBrandTerm).where(AiBrandTerm.project_id == project.id).order_by(AiBrandTerm.id)):
        by_owner[term.owner].append(term.term)
    own = list(by_owner.get(project.domain, []))
    if project.name and project.name != project.domain and project.name not in own:
        own.append(project.name)
    brands = [Brand(project.domain, True, tuple(own), project.domain)]
    for domain in session.scalars(select(Competitor.domain).where(Competitor.project_id == project.id).order_by(Competitor.id)):
        brands.append(Brand(domain, False, tuple(by_owner.get(domain, [])), domain))
    return brands


def run_project(project_id: int, providers=None, trigger: str = "manual", factory=None) -> Dict[str, Any]:
    factory = factory or get_session_factory()
    providers = providers if providers is not None else configured_providers()
    with factory() as session:
        project = session.get(Project, project_id)
        prompts = [(p.id, p.text) for p in session.scalars(select(AiPrompt).where(
            AiPrompt.project_id == project_id, AiPrompt.enabled.is_(True)).order_by(AiPrompt.id))]
        brands = load_brands(session, project)
    if not prompts:
        return {"status": "no_prompts"}
    if not providers:
        return {"status": "not_configured"}
    dry = any(p.dry_run for p in providers)
    with factory.begin() as session:
        run = AiRun(project_id=project_id, started_at=utcnow(), trigger=trigger, dry_run=dry, calls=0, errors=0)
        session.add(run)
        session.flush()
        run_id = run.id

    hint = [((b.terms[0] if b.terms else b.domain), b.domain) for b in brands]
    jobs = [(prompt_id, text, provider) for prompt_id, text in prompts for provider in providers]

    def call(job):
        _, text, provider = job
        try:
            return provider.ask(text, brands_hint=hint)
        except Exception as exc:
            logger.error("%s failed on a prompt: %s", provider.name, exc, exc_info=exc)
            return Answer(model=provider.model, error=f"unexpected error ({type(exc).__name__})")

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        answers = list(pool.map(call, jobs))

    now, rows, errors, ok, mentions = utcnow(), [], 0, 0, 0
    for (prompt_id, text, provider), answer in zip(jobs, answers):
        if answer.error:
            errors += 1
            facts = {"mentioned": False, "position": None, "brands_mentioned": [], "cited": False}
        else:
            facts = analyze(answer.text, answer.citations, brands)
            ok += 1
            mentions += int(facts["mentioned"])
        rows.append({"run_id": run_id, "project_id": project_id, "ran_at": now, "provider": provider.name,
                     "model": (answer.model or provider.model or "")[:64], "prompt": text, "prompt_id": prompt_id,
                     "answer": (answer.text or "")[:MAX_ANSWER], "mentioned": facts["mentioned"],
                     "position": facts["position"], "brands_json": facts["brands_mentioned"], "cited": facts["cited"],
                     "citations_json": answer.citations[:20], "error": answer.error, "dry_run": provider.dry_run,
                     "result_json": {}})
    with factory.begin() as session:
        session.execute(insert(AiVisibilityRun), rows)
        run = session.get(AiRun, run_id)
        run.finished_at, run.calls, run.errors = now, len(rows), errors
        session.get(Project, project_id).last_ai_run_at = now
    return {"status": "ran", "run_id": run_id, "calls": len(rows), "errors": errors, "dry_run": dry,
            "mention_rate": round(mentions / ok, 3) if ok else None}
