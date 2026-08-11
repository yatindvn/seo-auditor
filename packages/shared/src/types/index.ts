export interface Recommendation {
  code: string;
  severity: "critical" | "warning" | "info";
  affected_pages: number;
  example_urls: string[];
  recommendation: string;
  priority_score: number;
  impact?: "High" | "Medium" | "Low";
  estimated_effort?: "Quick Win" | "Moderate" | "Major";
  description?: string;
  suggested_resolution?: string;
}

export interface CategoryScores {
  technical_seo: number;
  content: number;
  internal_linking: number;
  accessibility: number;
  performance: number;
  security: number;
}

export interface HealthScore {
  score: number;
  grade: "A" | "B" | "C" | "D" | "F";
  critical_issues: number;
  warning_issues: number;
  info_issues: number;
  categories?: CategoryScores;
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
  robots_txt_content?: string | null;
  sitemap_urls?: string[];
}

export interface KeywordRanking {
  keyword: string;
  position: number | null;
  note?: string;
  checked_at?: string;
}

export interface SuggestedKeyword {
  phrase: string;
  reason: string;
  competitor_examples?: string[];
}

export interface KeywordAnalysis {
  top_keywords: { phrase: string; score: number | null; found_in: string[] }[];
  rankings: KeywordRanking[];
  suggested_keywords: SuggestedKeyword[];
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

  // Rich Page Data (Phase 1)
  redirect_chain?: Array<{ from: string; to: string; status: number }>;
  redirect_count?: number;
  meta_robots?: string | null;
  lang?: string | null;
  open_graph?: Record<string, string>;
  twitter_cards?: Record<string, string>;
  h2_count?: number;
  h3_count?: number;
  heading_hierarchy?: Array<{ level: number; text: string }>;
  char_count?: number;
  reading_time_mins?: number;
  html_size_bytes?: number;
  internal_links_count?: number;
  external_links_count?: number;
  images_count?: number;
  missing_alt_count?: number;
  structured_data?: Array<{ type: string; raw: string }>;
  last_modified?: string | null;
  security_headers?: Record<string, string | boolean>;
  seo_score?: number;
  keyword_analysis?: KeywordAnalysis;
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
  most_linked_pages?: Array<{ url: string; count: number }>;
  least_linked_pages?: Array<{ url: string; count: number }>;
}

export interface ArchitectureNode {
  id: string;
  url: string;
  label: string;
  depth: number;
  isBroken: boolean;
  isOrphan: boolean;
  isDeadEnd: boolean;
  isDeep: boolean;
  isHub: boolean;
  inboundCount: number;
  outboundCount: number;
}

export interface ArchitectureLink {
  source: string;
  target: string;
}

export interface SiteArchitecture {
  nodes: ArchitectureNode[];
  links: ArchitectureLink[];
  tree: any;
}

export interface AuditResponse {
  executive_summary: ExecutiveSummary;
  pages: PageItem[];
  recommendations: Recommendation[];
  duplicates: Duplicates;
  broken_links: BrokenLink[];
  site_wide_analysis: SiteWideAnalysis;
  architecture?: SiteArchitecture;
  elapsed_seconds: number;
  note: string;
}

export interface AuditRequestParams {
  url: string;
  max_pages?: number;
  max_depth?: number;
  ignore_robots?: boolean;
  enable_keyword_analysis?: boolean;
  enable_rank_check?: boolean;
  enable_competitor_gap?: boolean;
  target_keywords?: string[] | null;
}

export interface CrawlPage {
  url: string;
  status: number | null;
  depth: number;
  response_time: number | null;
  title?: string;
  issues_count?: number;
  timestamp?: string;
}

export interface LinkData {
  source: string;
  target: string;
  external: boolean;
  status?: number;
}

export interface CrawlStatus {
  stage: string;
  progress: number;
  pages_crawled: number;
  current_url?: string;
  completed: boolean;
  error?: string;
  current_depth?: number;
  queue_remaining?: number;
  speed_pages_per_sec?: number;
  elapsed_seconds?: number;
  eta_seconds?: number;
}

export interface ActivityLogEvent {
  id: string;
  type: "page_crawled" | "internal_link" | "external_link" | "broken_link" | "redirect" | "error" | "warning";
  message: string;
  timestamp: string;
  url?: string;
}

export interface HistoricalComparison {
  previousDate: string;
  currentDate: string;
  scoreChange: number;
  previousScore: number;
  currentScore: number;
  newIssuesCount: number;
  resolvedIssuesCount: number;
  newIssues: string[];
  resolvedIssues: string[];
  pagesCountDelta: number;
}

export interface Issue {
  id: string;
  code: string;
  severity: "critical" | "warning" | "info";
  message: string;
  affected_url: string;
  description?: string;
  priority?: number;
  impact?: string;
  effort?: string;
  suggested_resolution?: string;
}

export interface DashboardStats {
  healthScore: number;
  pagesCrawled: number;
  criticalIssues: number;
  warningIssues: number;
  infoIssues: number;
}

export interface CrawlResult {
  jobId: string;
  url: string;
  status: "pending" | "running" | "completed" | "failed";
  data?: AuditResponse;
  error?: string;
}
