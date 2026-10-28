"""Custom rules (Phase 5.4): create, edit, test, and read an audit's summary."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body, HTTPException, Response
from sqlalchemy import func, select

from app.api.projects import _factory
from app.auditor import checks
from app.crawler.crawler import Crawler, PageResult
from app.db.models import Audit, CustomRule, Project, as_utc
from app.db.projects import project_domain
from app.rules import engine
from app.rules.schema import RuleError, validate_rule
from app.services import page_pipeline

router = APIRouter()
MAX_RULES = 50


def _json(row: CustomRule) -> Dict[str, Any]:
    return {"id": row.id, "project_id": row.project_id, "name": row.name, "enabled": row.enabled,
            "severity": row.severity, "message": row.message or "", "url_pattern": row.url_pattern,
            "check": row.check_json, "description": engine.describe(row.check_json),
            "created_at": as_utc(row.created_at).isoformat(), "updated_at": as_utc(row.updated_at).isoformat()}


def _valid(data: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return validate_rule(data)
    except RuleError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _project(session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


@router.get("/projects/{project_id}/rules")
def list_rules(project_id: int):
    with _factory()() as session:
        _project(session, project_id)
        rows = session.scalars(select(CustomRule).where(CustomRule.project_id == project_id).order_by(CustomRule.id)).all()
        return {"items": [_json(r) for r in rows]}


@router.post("/projects/{project_id}/rules", status_code=201)
def create_rule(project_id: int, body: Dict[str, Any] = Body(...)):
    rule = _valid(body)
    with _factory().begin() as session:
        _project(session, project_id)
        count = session.scalar(select(func.count()).select_from(CustomRule).where(CustomRule.project_id == project_id))
        if count >= MAX_RULES:
            raise HTTPException(status_code=409, detail=f"a project can have at most {MAX_RULES} rules")
        row = CustomRule(project_id=project_id, name=rule["name"], enabled=rule["enabled"], severity=rule["severity"],
                         message=rule["message"], url_pattern=rule["url_pattern"], check_json=rule["check"])
        session.add(row)
        session.flush()
        return _json(row)


@router.patch("/rules/{rule_id}")
def update_rule(rule_id: int, body: Dict[str, Any] = Body(...)):
    with _factory().begin() as session:
        row = session.get(CustomRule, rule_id)
        if row is None:
            raise HTTPException(status_code=404, detail="rule not found")
        merged = {"name": row.name, "enabled": row.enabled, "severity": row.severity, "message": row.message,
                  "url_pattern": row.url_pattern, "check": row.check_json}
        merged.update({k: v for k, v in body.items() if k in merged})
        rule = _valid(merged)
        row.name, row.enabled, row.severity = rule["name"], rule["enabled"], rule["severity"]
        row.message, row.url_pattern, row.check_json = rule["message"], rule["url_pattern"], rule["check"]
        session.flush()
        return _json(row)


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int):
    with _factory().begin() as session:
        row = session.get(CustomRule, rule_id)
        if row is None:
            raise HTTPException(status_code=404, detail="rule not found")
        session.delete(row)
    return Response(status_code=204)


def fetch_page(url: str) -> PageResult:
    """One page, fetched the way an audit fetches it."""
    crawler = Crawler(start_url=url, max_pages=1, max_depth=0, timeout=15, retries=1)
    return crawler._fetch(url, conditional=False)


@router.post("/projects/{project_id}/rules/test")
def test_rule(project_id: int, body: Dict[str, Any] = Body(...)):
    url = str(body.get("url") or "").strip()
    rule = _valid(body.get("rule") or {})
    with _factory()() as session:
        domain = _project(session, project_id).domain
    if not url.startswith(("http://", "https://")) or project_domain(url) != domain:
        raise HTTPException(status_code=400, detail=f"the URL must be on {domain}")
    page = fetch_page(url)
    if page.error or page.status_code is None:
        raise HTTPException(status_code=502, detail=f"could not fetch {url}: {page.error or 'no response'}")
    view = {"id": 0, **{k: rule[k] for k in ("name", "severity", "message", "url_pattern", "check")}}
    if not engine.applies(view, url):
        return {"applies": False, "passed": None, "observed": None, "issue": None}
    analysis = page_pipeline.analyze_page(page_pipeline.PagePayload(
        url=url, final_url=page.final_url or url, status_code=page.status_code, headers=page.headers or {},
        html=page.html or "", response_time_ms=page.response_time_ms, content_type=page.content_type or "",
        enable_keyword_analysis=False, custom_rules=[view]))
    facts = engine.PageFacts(url=url, meta=analysis.meta, text=analysis.dupe_row.get("text") or "",
                             html=page.html or "", soup=checks._soup(page.html or ""),
                             status=page.status_code, response_time_ms=page.response_time_ms)
    found = next((i for i in analysis.issues if i.get("source") == "custom"), None)
    return {"applies": True, "passed": found is None, "observed": engine.observe(view["check"], facts), "issue": found}


@router.get("/audits/{audit_id}/custom-rules")
def audit_custom_rules(audit_id: int):
    with _factory()() as session:
        audit = session.get(Audit, audit_id)
        if audit is None:
            raise HTTPException(status_code=404, detail="audit not found")
        return {"audit_id": audit_id, "items": (audit.summary_json or {}).get("custom_rules") or []}
