"""Projects, audit history and diffs, read from the central database."""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db import engine as db_engine
from app.db.diff import diff_audits, previous_audit_id
from app.db.models import Audit, Project
from app.db.projects import project_domain

router = APIRouter()
logger = logging.getLogger("seo_auditor")

Schedule = Optional[Literal["daily", "weekly"]]


class ProjectCreate(BaseModel):
    domain: str
    name: Optional[str] = None
    audit_schedule: Schedule = None
    audit_options: Dict[str, Any] = {}


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    audit_schedule: Schedule = None
    audit_options: Optional[Dict[str, Any]] = None


def _factory():
    try:
        return db_engine.get_session_factory()
    except Exception as exc:
        logger.error("Central database unavailable: %s", exc, exc_info=exc)
        raise HTTPException(status_code=503, detail="central database unavailable")


def _audit_json(audit: Audit) -> Dict[str, Any]:
    return {
        "id": audit.id, "session_id": audit.session_id, "status": audit.status,
        "trigger": audit.trigger, "start_url": audit.start_url,
        "started_at": audit.started_at.isoformat(), "finished_at": audit.finished_at.isoformat(),
        "page_count": audit.page_count, "health_score": audit.health_score,
    }


def _project_json(session, project: Project) -> Dict[str, Any]:
    latest = session.scalar(select(Audit).where(Audit.project_id == project.id)
                            .order_by(Audit.finished_at.desc(), Audit.id.desc()).limit(1))
    count = session.scalar(select(func.count()).select_from(Audit).where(Audit.project_id == project.id))
    return {
        "id": project.id, "name": project.name, "domain": project.domain,
        "audit_schedule": project.audit_schedule, "audit_options": project.audit_options_json,
        "audit_count": count,
        "latest_audit": None if latest is None else {
            "id": latest.id, "finished_at": latest.finished_at.isoformat(),
            "health_score": latest.health_score,
        },
    }


@router.get("/projects")
def list_projects():
    with _factory()() as session:
        projects = session.scalars(select(Project).order_by(Project.domain)).all()
        return {"items": [_project_json(session, p) for p in projects]}


@router.post("/projects", status_code=201)
def create_project(body: ProjectCreate):
    domain = project_domain(body.domain)
    try:
        with _factory().begin() as session:
            project = Project(name=body.name or domain, domain=domain,
                              audit_schedule=body.audit_schedule,
                              audit_options_json=body.audit_options)
            session.add(project)
            session.flush()
            return _project_json(session, project)
    except IntegrityError:
        raise HTTPException(status_code=409, detail=f"a project for {domain} already exists")


@router.patch("/projects/{project_id}")
def update_project(project_id: int, body: ProjectUpdate):
    with _factory().begin() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="no such project")
        fields = body.model_dump(exclude_unset=True)
        if "name" in fields:
            project.name = fields["name"]
        if "audit_schedule" in fields:
            project.audit_schedule = fields["audit_schedule"]
        if fields.get("audit_options") is not None:
            project.audit_options_json = fields["audit_options"]
        session.flush()
        return _project_json(session, project)


@router.get("/projects/{project_id}/audits")
def list_project_audits(project_id: int, offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=200)):
    with _factory()() as session:
        if session.get(Project, project_id) is None:
            raise HTTPException(status_code=404, detail="no such project")
        where = Audit.project_id == project_id
        total = session.scalar(select(func.count()).select_from(Audit).where(where))
        audits = session.scalars(select(Audit).where(where)
                                 .order_by(Audit.finished_at.desc(), Audit.id.desc())
                                 .offset(offset).limit(limit)).all()
        return {"items": [_audit_json(a) for a in audits], "total": total,
                "offset": offset, "limit": limit}


@router.get("/audits/{audit_id}/diff")
def audit_diff(audit_id: int, against: Optional[int] = None, limit: int = Query(500, ge=1, le=5000)):
    with _factory()() as session:
        if session.get(Audit, audit_id) is None:
            raise HTTPException(status_code=404, detail="no such audit")
        old_id = against if against is not None else previous_audit_id(session, audit_id)
        if old_id is None:
            raise HTTPException(status_code=404, detail="no earlier audit of this project to compare with")
        try:
            return diff_audits(session, old_id, audit_id, limit=limit)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
