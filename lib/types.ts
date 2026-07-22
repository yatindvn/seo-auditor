export interface Recommendation {
  code: string;
  severity: "critical" | "warning" | "info";
  affected_pages: number;
  example_urls: string[];
  recommendation: string;
  priority_score: number;
}

export interface HealthScore {
  score: number;
  grade: "A" | "B" | "C" | "D" | "F";
  critical_issues: number;
  warning_issues: number;
  info_issues: number;
}

export interface ExecutiveSummary {
  audit_date: string;
  start_url: string;
  pages_crawled: number;
  health_score: HealthScore;
  status_code_breakdown: Record<string, number>;
  orphan_pages: number;
  broken_links: number;
  redirect_chains: number;
  redirect_loops: number;
  duplicate_titles: number;
  duplicate_meta_descriptions: number;
  duplicate_content_groups: number;
  top_recommendations: Recommendation[];
  robots_txt_found: boolean;
  sitemaps_found: string[];
  sitemap_url_count: number;
}

export interface PageItem {
  url: string;
  status_code: number | null;
  depth: number;
  response_time_ms: number | null;
  title: string | null;
  meta_description: string | null;
  h1: string | null;
  word_count: number;
  canonical: string | null;
  critical_issues: number;
  warning_issues: number;
  info_issues: number;
  issue_codes: string;
}

export interface Duplicates {
  duplicate_titles: Record<string, string[]>;
  duplicate_meta_descriptions: Record<string, string[]>;
  duplicate_h1: Record<string, string[]>;
  duplicate_content: Record<string, string[]>;
  duplicate_canonicals: Record<string, string[]>;
}

export interface BrokenLink {
  url: string;
  status: number | null;
  error: string | null;
  linked_from: string[];
  linked_from_count: number;
  external?: boolean;
}

export interface TopPageImportance {
  url: string;
  score: number;
}

export interface SiteWideAnalysis {
  total_pages: number;
  orphan_pages: string[];
  orphan_count: number;
  dead_end_pages: string[];
  dead_end_count: number;
  hub_pages_over_linked: Array<[string, number]>;
  max_crawl_depth: number;
  depth_distribution: Record<string, number>;
  top_pages_by_importance: TopPageImportance[];
  pagerank_available: boolean;
}

export interface AuditResponse {
  executive_summary: ExecutiveSummary;
  pages: PageItem[];
  recommendations: Recommendation[];
  duplicates: Duplicates;
  broken_links: BrokenLink[];
  site_wide_analysis: SiteWideAnalysis;
  elapsed_seconds: number;
  note: string;
}

export interface AuditRequestParams {
  url: string;
  max_pages?: number;
  max_depth?: number;
  ignore_robots?: boolean;
}
