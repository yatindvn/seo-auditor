"""Central database models. The schema itself is owned by the Alembic
migration in apps/backend/alembic; tests assert the two agree."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite returns naive datetimes even for timezone=True columns; every
    value stored here is UTC, so a naive one is UTC too."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    domain: Mapped[str] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    audit_schedule: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    audit_options_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    last_scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    audits = relationship("Audit", back_populates="project")


class Audit(Base):
    __tablename__ = "audits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    session_id: Mapped[str] = mapped_column(String(64), unique=True)
    start_url: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    trigger: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    health_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    summary_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    project = relationship("Project", back_populates="audits")


class AuditPage(Base):
    __tablename__ = "audit_pages"
    __table_args__ = (UniqueConstraint("audit_id", "url", name="uq_audit_pages_audit_url"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(Text)
    final_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    depth: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    word_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    issue_count: Mapped[int] = mapped_column(Integer, default=0)
    alias_of: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duplicate_of: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cache_status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)


class AuditIssue(Base):
    __tablename__ = "audit_issues"
    __table_args__ = (
        Index("ix_audit_issues_audit_code", "audit_id", "code"),
        Index("ix_audit_issues_audit_url", "audit_id", "url"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(Text)
    code: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text)


class Keyword(Base):
    __tablename__ = "keywords"
    __table_args__ = (
        UniqueConstraint("project_id", "phrase", "country", "device", name="uq_keywords_identity"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    phrase: Mapped[str] = mapped_column(String(255))
    country: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    device: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    target_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class RankCheck(Base):
    __tablename__ = "rank_checks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keyword_id: Mapped[int] = mapped_column(ForeignKey("keywords.id"), index=True)
    audit_id: Mapped[Optional[int]] = mapped_column(ForeignKey("audits.id", ondelete="SET NULL"), nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provider: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    position: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ranking_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Competitor(Base):
    __tablename__ = "competitors"
    __table_args__ = (UniqueConstraint("project_id", "domain", name="uq_competitors_project_domain"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    domain: Mapped[str] = mapped_column(String(255))


class BacklinkSnapshot(Base):
    __tablename__ = "backlink_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provider: Mapped[str] = mapped_column(String(32))
    metrics_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)


class AiVisibilityRun(Base):
    __tablename__ = "ai_visibility_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provider: Mapped[str] = mapped_column(String(32))
    prompt: Mapped[str] = mapped_column(Text)
    result_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
