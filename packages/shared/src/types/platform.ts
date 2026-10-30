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
  gsc_property?: string | null;
  last_gsc_sync_at?: string | null;
  backlink_schedule?: "weekly" | null;
  ai_schedule?: "weekly" | null;
  last_ai_run_at?: string | null;
  last_backlink_refresh_at?: string | null;
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

// Custom rules (backend Phase 5.4).
export type RuleSeverity = "critical" | "warning" | "info";
export type RuleCheck =
  | { type: "field"; field: string; op: string; value?: string | number | null }
  | { type: "text"; scope: "visible" | "html"; op: "contains" | "not_contains"; value: string; case_sensitive?: boolean }
  | { type: "selector"; selector: string; op: string; value?: number | null };

export interface NewRule {
  name: string;
  enabled?: boolean;
  severity: RuleSeverity;
  message: string;
  url_pattern: string | null;
  check: RuleCheck;
}

export interface CustomRule extends Required<Omit<NewRule, "enabled">> {
  id: number;
  project_id: number;
  enabled: boolean;
  description: string;
  created_at: string;
  updated_at: string;
}

export interface RuleTestResult {
  applies: boolean;
  passed: boolean | null;
  observed: string | number | boolean | null;
  issue: { severity: string; code: string; message: string } | null;
}

export interface RuleSummary {
  rule_id: number;
  name: string;
  severity: RuleSeverity;
  description: string;
  pages_checked: number;
  pages_failed: number;
  example_urls: string[];
}

// Google Search Console (backend Phase 5.5).
export interface GscKpis { clicks: number; impressions: number; ctr: number | null; position: number | null }
export interface GscDailyPoint { date: string; clicks: number; impressions: number; ctr: number; position: number }
export interface GscOverview {
  configured: boolean; dry_run: boolean; client_email: string | null; property: string | null;
  last_sync_at: string | null; kpis: GscKpis | null; previous_kpis: GscKpis | null; daily: GscDailyPoint[];
}
export interface GscRow { key: string; clicks: number; impressions: number; ctr: number; position: number }
export interface GscList { total: number; items: GscRow[] }
export type GscSort = "clicks" | "impressions" | "ctr" | "position";
export interface GscSyncResult {
  status: "synced" | "no_access" | "error"; property: string | null; message?: string; client_email?: string | null;
  days?: number; pages?: number; queries?: number; dry_run: boolean;
}
export interface GscSites { configured: boolean; dry_run: boolean; client_email: string | null; sites: { site_url: string; permission: string }[] }
export interface GscInspectionRow {
  url: string; verdict: string | null; coverage_state: string | null; indexing_state: string | null; robots_state: string | null;
  fetch_state: string | null; google_canonical: string | null; user_canonical: string | null; last_crawl: string | null; error: string | null;
}
export interface AuditGsc {
  audit_id: number; status: "inspected" | "disabled" | "not_configured" | "no_property" | "error";
  property: string | null; dry_run: boolean; inspections: GscInspectionRow[];
  pages: { url: string; clicks: number; impressions: number; ctr: number; position: number; inspection_verdict: string | null }[];
  not_crawled: { url: string; clicks: number; impressions: number }[];
}

// Backlinks (backend Phase 6, DataForSEO).
export interface BacklinkTotals { taken_at: string; authority: number | null; backlinks: number; referring_domains: number; broken_backlinks: number; dry_run: boolean }
export interface BacklinkOverview {
  dry_run_provider: boolean; schedule: "weekly" | null; last_refresh_at: string | null;
  latest: BacklinkTotals | null; previous: BacklinkTotals | null;
  history: { date: string; authority: number | null; backlinks: number; referring_domains: number; source: "snapshot" | "history" }[];
}
export interface RefDomainRow { domain: string; rank: number | null; backlinks: number; first_seen: string | null }
export interface BacklinkRow {
  url_from: string; url_to: string; anchor: string; domain_from_rank: number | null; dofollow: boolean;
  first_seen: string | null; last_seen: string | null; target_status: number | null; crawled_status?: number | null;
}
export type BacklinkKind = "new" | "lost" | "broken";
export interface BacklinkRefresh { status: "refreshed" | "capped" | "error"; snapshot_id?: number; dry_run: boolean; history_months?: number; message?: string }
export interface LinkGapRow { domain: string; rank: number | null; linked_count: number; backlinks_by_competitor: Record<string, number> }
export interface LinkGapResult { my_domain: string; competitors: string[]; dry_run: boolean; rows: LinkGapRow[] }

// AI Visibility (backend Phase 7.1).
export interface AiProviderStatus { name: string; model: string | null; dry_run: boolean; configured: boolean; hint: string | null }
export interface AiRates { mention_rate: number | null; avg_position: number | null; cited_rate: number | null }
export interface AiRunSummary extends AiRates {
  run_id: number; started_at: string; dry_run: boolean; calls: number; errors: number; by_provider: Record<string, AiRates>;
}
export interface AiOverview {
  providers: AiProviderStatus[]; dry_run: boolean; schedule: "weekly" | null; last_run_at: string | null;
  latest: AiRunSummary | null; previous: AiRunSummary | null;
  trend: { run_id: number; started_at: string; mention_rate: number | null; by_provider: Record<string, number | null> }[];
  share_of_voice: { owner: string; is_self: boolean; rate: number }[];
  top_cited: { domain: string; count: number; is_self: boolean }[];
}
export interface AiPrompt { id: number; text: string; enabled: boolean }
export interface AiBrands { self: { domain: string; terms: string[] }; competitors: { domain: string; terms: string[] }[] }
export interface AiAnswer {
  id: number; prompt: string; provider: string; model: string; mentioned: boolean; position: number | null; brands: string[];
  cited: boolean; citations: { url: string; title: string }[]; error: string | null; answer: string;
  highlights: { start: number; end: number; owner: string }[];
}
export interface AiRunResult { status: "ran" | "no_prompts" | "not_configured"; run_id?: number; calls?: number; errors?: number; dry_run?: boolean; mention_rate?: number | null }
