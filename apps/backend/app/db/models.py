"""Central database models. The schema itself is owned by the Alembic
migration in apps/backend/alembic; tests assert the two agree."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, false, true,
)
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
    rank_schedule: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    last_rank_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    alert_settings_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    gsc_property: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_gsc_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    backlink_schedule: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    last_backlink_refresh_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ai_schedule: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    last_ai_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

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
    language: Mapped[str] = mapped_column(String(8), default="en", server_default="en")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=True)


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
    serp_json: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSON, nullable=True)
    competitor_positions_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)


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
    authority: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    backlinks: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    referring_domains: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    broken_backlinks: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    source: Mapped[str] = mapped_column(String(16), default="snapshot", server_default="snapshot")
    period: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class AiVisibilityRun(Base):
    __tablename__ = "ai_visibility_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provider: Mapped[str] = mapped_column(String(32))
    prompt: Mapped[str] = mapped_column(Text)
    result_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    run_id: Mapped[Optional[int]] = mapped_column(ForeignKey("ai_runs.id", ondelete="CASCADE", name="fk_ai_visibility_runs_run_id"), nullable=True, index=True)
    prompt_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    model: Mapped[str] = mapped_column(String(64), default="", server_default="")
    answer: Mapped[str] = mapped_column(Text, default="", server_default="")
    mentioned: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    position: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    brands_json: Mapped[Optional[List[str]]] = mapped_column(JSON, default=list, nullable=True)
    cited: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    citations_json: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSON, default=list, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class ProviderUsage(Base):
    """Paid-call counter per provider per UTC day: what the spend guard caps."""
    __tablename__ = "provider_usage"
    __table_args__ = (UniqueConstraint("provider", "day", name="uq_provider_usage_provider_day"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    day: Mapped[date] = mapped_column(Date)
    calls: Mapped[int] = mapped_column(Integer, default=0)


class Alert(Base):
    """One alert per (rank check, kind, channel): inserted before sending, so
    the unique constraint makes a repeated run unable to send it twice."""
    __tablename__ = "alerts"
    __table_args__ = (UniqueConstraint("rank_check_id", "kind", "channel", name="uq_alerts_check_kind_channel"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    keyword_id: Mapped[int] = mapped_column(ForeignKey("keywords.id"))
    rank_check_id: Mapped[int] = mapped_column(ForeignKey("rank_checks.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))
    channel: Mapped[str] = mapped_column(String(16))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)


class ProviderCache(Base):
    """A provider response, reused until it expires so a repeat costs nothing."""
    __tablename__ = "provider_cache"
    __table_args__ = (
        UniqueConstraint("provider", "endpoint", "request_hash", name="uq_provider_cache_request"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    endpoint: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    response_json: Mapped[Any] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WebVital(Base):
    """One page's Core Web Vitals in one audit (Phase 5.1)."""
    __tablename__ = "web_vitals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)
    strategy: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(16))
    data_kind: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    rating: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    performance_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lcp_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    inp_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cls: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fcp_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ttfb_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tbt_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RenderedPage(Base):
    """One page's raw-vs-rendered comparison in one audit (Phase 5.2)."""
    __tablename__ = "render_comparisons"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    render_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    raw_word_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rendered_word_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    changes_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    js_only_links_json: Mapped[List[str]] = mapped_column(JSON, default=list)
    js_only_links_count: Mapped[int] = mapped_column(Integer, default=0)


class AccessibilityScan(Base):
    """One page's axe-core scan in one audit (Phase 5.3)."""
    __tablename__ = "accessibility_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    critical: Mapped[int] = mapped_column(Integer, default=0)
    serious: Mapped[int] = mapped_column(Integer, default=0)
    moderate: Mapped[int] = mapped_column(Integer, default=0)
    minor: Mapped[int] = mapped_column(Integer, default=0)
    violations_json: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)


class CustomRule(Base):
    """A user-defined check, evaluated on every page of the project's audits (Phase 5.4)."""
    __tablename__ = "custom_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    severity: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(String(200), default="")
    url_pattern: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    check_json: Mapped[Dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class GscDaily(Base):
    """One day of a project's Search Console totals (Phase 5.5), kept past
    Google's 16-month window."""
    __tablename__ = "gsc_daily"
    __table_args__ = (UniqueConstraint("project_id", "date", name="uq_gsc_daily_project_date"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date)
    clicks: Mapped[float] = mapped_column(Float)
    impressions: Mapped[float] = mapped_column(Float)
    ctr: Mapped[float] = mapped_column(Float)
    position: Mapped[float] = mapped_column(Float)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)


class GscPage(Base):
    """The latest 28-day Search Console numbers per page (replaced on each sync)."""
    __tablename__ = "gsc_pages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)
    clicks: Mapped[float] = mapped_column(Float)
    impressions: Mapped[float] = mapped_column(Float)
    ctr: Mapped[float] = mapped_column(Float)
    position: Mapped[float] = mapped_column(Float)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)


class GscQuery(Base):
    """The latest 28-day Search Console numbers per query (replaced on each sync)."""
    __tablename__ = "gsc_queries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    query: Mapped[str] = mapped_column(Text)
    clicks: Mapped[float] = mapped_column(Float)
    impressions: Mapped[float] = mapped_column(Float)
    ctr: Mapped[float] = mapped_column(Float)
    position: Mapped[float] = mapped_column(Float)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)


class GscInspection(Base):
    """One page's URL Inspection result in one audit."""
    __tablename__ = "gsc_inspections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)
    verdict: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    coverage_state: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    indexing_state: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    robots_state: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    fetch_state: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    google_canonical: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_canonical: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_crawl: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)


class BacklinkRefDomain(Base):
    """A top referring domain in one backlink snapshot (Phase 6)."""
    __tablename__ = "backlink_ref_domains"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("backlink_snapshots.id", ondelete="CASCADE"), index=True)
    domain: Mapped[str] = mapped_column(String(255))
    rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    backlinks: Mapped[int] = mapped_column(Integer, default=0)
    first_seen: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)


class BacklinkLink(Base):
    """A new, lost or broken backlink in one snapshot."""
    __tablename__ = "backlink_links"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("backlink_snapshots.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(8))
    url_from: Mapped[str] = mapped_column(Text)
    url_to: Mapped[str] = mapped_column(Text)
    anchor: Mapped[str] = mapped_column(Text, default="")
    domain_from_rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    dofollow: Mapped[bool] = mapped_column(Boolean, default=True)
    first_seen: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    last_seen: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    target_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class AiPrompt(Base):
    """A question tracked for AI Visibility (Phase 7.1)."""
    __tablename__ = "ai_prompts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AiBrandTerm(Base):
    """A name or alias a brand (the project's or a competitor's) is matched by."""
    __tablename__ = "ai_brand_terms"
    __table_args__ = (UniqueConstraint("project_id", "owner", "term", name="uq_ai_brand_terms_owner_term"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    owner: Mapped[str] = mapped_column(String(255))
    term: Mapped[str] = mapped_column(String(100))


class AiRun(Base):
    """One AI Visibility run: every enabled prompt asked of every model."""
    __tablename__ = "ai_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    trigger: Mapped[str] = mapped_column(String(16))
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    calls: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
