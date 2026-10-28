// Central-database and keyword-research API shapes (backend Phases 1-3).

export interface AlertSettings {
  drop_threshold?: number;
  top10_alerts?: boolean;
  gain_threshold?: number | null;
}

export interface ProjectSummary {
  id: number;
  name: string;
  domain: string;
  audit_schedule: "daily" | "weekly" | null;
  audit_options: Record<string, unknown>;
  rank_schedule: "daily" | null;
  alert_settings: AlertSettings;
  audit_count: number;
  latest_audit: { id: number; finished_at: string; health_score: number | null } | null;
}

export interface PageList<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

export interface AuditListItem {
  id: number;
  session_id: string;
  status: "completed" | "partial" | "failed";
  trigger: "manual" | "scheduled" | "import";
  start_url: string;
  started_at: string;
  finished_at: string;
  page_count: number;
  health_score: number | null;
}

export interface DiffIssue {
  url: string;
  code: string;
  severity: string;
  message: string;
}

export interface AuditDiff {
  old_audit_id: number;
  new_audit_id: number;
  health_score_change: number | null;
  issues: { new: DiffIssue[]; fixed: DiffIssue[]; new_count: number; fixed_count: number; persisting_count: number };
  pages: {
    added: string[];
    removed: string[];
    status_changed: { url: string; old_status: number | null; new_status: number | null }[];
    added_count: number;
    removed_count: number;
    status_changed_count: number;
  };
}

export interface RankCheckView {
  position: number | null;
  ranking_url: string | null;
  status: "ranked" | "not_ranked" | "skipped";
  checked_at: string;
  note: string | null;
  competitor_positions: Record<string, number | null>;
}

export interface TrackedKeyword {
  id: number;
  phrase: string;
  country: string;
  device: "desktop" | "mobile";
  language: string;
  enabled: boolean;
  latest: RankCheckView | null;
  /** previous position minus latest: positive = improved */
  change: number | null;
}

export interface CompetitorDomain {
  id: number;
  domain: string;
}

export interface RankPreview {
  dry_run: true;
  results: {
    phrase: string;
    position: number | null;
    ranking_url: string | null;
    competitor_positions: Record<string, number | null>;
  }[];
}

export interface ExploreKeyword {
  keyword: string;
  source: "seed" | "autocomplete" | "people_also_ask";
  search_volume: number | null;
  cpc: number | null;
  competition: string | null;
  difficulty: number | null;
  traffic_potential_estimate: number | null;
}

export interface ExploreResult {
  seed: string;
  country: string;
  language: string;
  dry_run: boolean;
  keywords: ExploreKeyword[];
  clusters: string[][];
  notes: string[];
}

export interface GapRow {
  keyword: string;
  search_volume: number | null;
  difficulty: number | null;
  opportunity: number;
  best_competitor_position: number;
  competitors: Record<string, { position: number; url: string }>;
}

export interface GapResult {
  my_domain: string;
  competitors: string[];
  dry_run: boolean;
  rows: GapRow[];
  total_gaps: number;
}

// Core Web Vitals (backend Phase 5.1).
export type VitalsRating = "good" | "needs_improvement" | "poor";
export type VitalsStatus = "measured" | "not_configured" | "disabled";
export type VitalsMetric = "lcp_ms" | "inp_ms" | "cls" | "tbt_ms";

export interface VitalsRow {
  url: string;
  strategy: string;
  source: "psi" | "lighthouse" | "not_measured";
  data_kind: "field" | "lab" | null;
  rating: VitalsRating | null;
  performance_score: number | null;
  lcp_ms: number | null;
  inp_ms: number | null;
  cls: number | null;
  fcp_ms: number | null;
  ttfb_ms: number | null;
  tbt_ms: number | null;
  error: string | null;
  measured_at?: string | null;
  metric_ratings: Record<VitalsMetric, VitalsRating | null>;
}

export interface AuditVitals { audit_id: number; status: VitalsStatus; items: VitalsRow[] }

export interface VitalsTrendPoint {
  audit_id: number;
  finished_at: string;
  url: string;
  source: VitalsRow["source"];
  data_kind: VitalsRow["data_kind"];
  performance_score: number | null;
  lcp_ms: number | null;
  inp_ms: number | null;
  cls: number | null;
  tbt_ms: number | null;
  rating: VitalsRating | null;
  metric_ratings: VitalsRow["metric_ratings"];
}

export interface VitalsTrend { url: string | null; points: VitalsTrendPoint[] }

// JavaScript rendering (backend Phase 5.2).
export type RenderStatus = "rendered" | "disabled" | "unavailable";
export interface RenderChange { raw: string | null; rendered: string | null }

export interface RenderComparison {
  url: string;
  status: "rendered" | "failed";
  error: string | null;
  render_ms: number | null;
  raw_word_count: number | null;
  rendered_word_count: number | null;
  changes: Partial<Record<"title" | "meta_description" | "canonical" | "meta_robots" | "h1", RenderChange>>;
  js_only_links: string[];
  js_only_links_count: number;
}

export interface AuditRendering { audit_id: number; status: RenderStatus; reason: string | null; items: RenderComparison[] }

// Accessibility (backend Phase 5.3, axe-core).
export type A11yImpact = "critical" | "serious" | "moderate" | "minor";
export type A11yStatus = "scanned" | "disabled" | "unavailable";

export interface A11yViolation {
  id: string;
  impact: A11yImpact;
  help: string;
  help_url: string | null;
  wcag: string[];
  nodes_count: number;
  targets: string[];
}

export interface A11yResult {
  url: string;
  status: "scanned" | "failed";
  error: string | null;
  score: number | null;
  counts: Record<A11yImpact, number>;
  violations: A11yViolation[];
}

export interface AuditAccessibility {
  audit_id: number;
  status: A11yStatus;
  reason: string | null;
  axe_version: string | null;
  items: A11yResult[];
}
