import type {
  AuditDiff, AuditListItem, CompetitorDomain, ExploreResult, GapResult, PageList,
  ProjectSummary, RankCheckView, RankPreview, TrackedKeyword, AlertSettings,
} from "@seo-auditor/shared";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || process.env.VITE_API_URL || "http://127.0.0.1:5000";

/** A failed API call. status 0 = the server could not be reached. */
export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/api${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    });
  } catch {
    throw new ApiError(0, "Could not reach the server");
  }
  if (res.status === 204) return undefined as T;
  let body: any = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  if (!res.ok) {
    throw new ApiError(res.status, typeof body?.detail === "string" ? body.detail : `Request failed (${res.status})`);
  }
  return body as T;
}

const post = (body?: unknown): RequestInit => ({
  method: "POST",
  body: body === undefined ? undefined : JSON.stringify(body),
});
const patch = (body: unknown): RequestInit => ({ method: "PATCH", body: JSON.stringify(body) });

export interface NewKeyword { phrase: string; country?: string; device?: "desktop" | "mobile" }

export const Platform = {
  listProjects: () => request<{ items: ProjectSummary[] }>("/projects"),
  updateProject: (id: number, body: Partial<{ name: string; rank_schedule: "daily" | null; alert_settings: AlertSettings }>) =>
    request<ProjectSummary>(`/projects/${id}`, patch(body)),
  listAudits: (id: number, limit = 50, offset = 0) =>
    request<PageList<AuditListItem>>(`/projects/${id}/audits?limit=${limit}&offset=${offset}`),
  auditDiff: (auditId: number, against?: number) =>
    request<AuditDiff>(`/audits/${auditId}/diff${against != null ? `?against=${against}` : ""}`),

  listKeywords: (id: number) => request<{ items: TrackedKeyword[] }>(`/projects/${id}/keywords`),
  addKeywords: (id: number, keywords: NewKeyword[]) =>
    request<{ created: number; skipped: number }>(`/projects/${id}/keywords`, post({ keywords })),
  setKeywordEnabled: (keywordId: number, enabled: boolean) =>
    request<{ id: number; enabled: boolean }>(`/keywords/${keywordId}`, patch({ enabled })),
  deleteKeyword: (keywordId: number) => request<void>(`/keywords/${keywordId}`, { method: "DELETE" }),
  keywordHistory: (keywordId: number, days = 90) =>
    request<{ items: RankCheckView[] }>(`/keywords/${keywordId}/history?days=${days}`),
  listCompetitors: (id: number) => request<{ items: CompetitorDomain[] }>(`/projects/${id}/competitors`),
  addCompetitor: (id: number, domain: string) =>
    request<CompetitorDomain>(`/projects/${id}/competitors`, post({ domain })),
  deleteCompetitor: (id: number, competitorId: number) =>
    request<void>(`/projects/${id}/competitors/${competitorId}`, { method: "DELETE" }),
  previewRankCheck: (id: number) => request<RankPreview>(`/projects/${id}/rank-checks/run`, post()),

  explore: (body: { seed: string; country?: string; language?: string; cluster?: boolean }) =>
    request<ExploreResult>("/keywords/explore", post(body)),
  exploreCsvUrl: (seed: string, country = "US", language = "en") =>
    `${API_BASE_URL}/api/keywords/explore.csv?${new URLSearchParams({ seed, country, language })}`,
  contentGap: (id: number, body: { competitors?: string[]; country?: string; language?: string; limit?: number }) =>
    request<GapResult>(`/projects/${id}/content-gap`, post(body)),
  contentGapCsvUrl: (id: number, competitors: string[], country = "US", language = "en", limit = 500) => {
    const params = new URLSearchParams({ country, language, limit: String(limit) });
    competitors.forEach((c) => params.append("competitor", c));
    return `${API_BASE_URL}/api/projects/${id}/content-gap.csv?${params}`;
  },
};
