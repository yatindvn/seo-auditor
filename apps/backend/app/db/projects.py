"""Projects are per domain: auditing a site files the audit under its project."""

from __future__ import annotations

import urllib.parse as up

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Project


def project_domain(url: str) -> str:
    """The lowercased host without `www.` or a port. Other subdomains are
    separate projects: blog.example.com is not example.com."""
    if "://" not in url:
        url = "https://" + url
    host = (up.urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def get_or_create_project(session: Session, url: str) -> Project:
    domain = project_domain(url)
    project = session.scalar(select(Project).where(Project.domain == domain))
    if project is None:
        project = Project(name=domain, domain=domain, audit_options_json={})
        session.add(project)
        session.flush()
    return project
