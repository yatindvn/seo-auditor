"""The audit fields that make up its summary: what /api/audit/latest serves and
what the central DB stores per audit. Page rows, issue detail and the graph are
never in it -- they have their own endpoints and tables."""

SUMMARY_FIELDS = (
    "executive_summary", "site_wide_analysis", "recommendations",
    "issue_frequency", "duplicates", "redirects", "rank_targets",
    "near_duplicate_mode", "elapsed_seconds", "degraded", "partial", "dedup", "reuse",
    "robots_txt", "sitemaps_found", "psi_metrics", "web_vitals", "web_vitals_status", "rendering", "render_status",
    "render_unavailable_reason", "accessibility", "accessibility_status",
    "accessibility_unavailable_reason", "axe_version", "custom_rules", "note",
    "audit_id", "project_id", "persisted",
)
