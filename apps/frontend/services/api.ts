import { AuditRequestParams, AuditResponse } from "@seo-auditor/shared";
import type { Paginated } from "@/lib/api-hooks";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || process.env.VITE_API_URL || "http://127.0.0.1:5000";
const WS_BASE_URL = process.env.NEXT_PUBLIC_WS_URL || process.env.VITE_WS_URL || "ws://localhost:5000/ws";

export class ApiService {
  public static async runAudit(params: AuditRequestParams): Promise<{ status: string, session_id: string }> {
    const endpoint = `${API_BASE_URL}/api/audit`;
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data?.detail || `Audit request failed with status ${res.status}`);
    }
    return data as { status: string, session_id: string };
  }

  public static async checkHealth(): Promise<{ status: string }> {
    const res = await fetch(`${API_BASE_URL}/api/health`);
    if (!res.ok) {
      throw new Error("Health check failed");
    }
    return res.json();
  }

  // These endpoints return a window of rows plus the unpaginated total, rather
  // than every row at once. A failure throws instead of returning an empty
  // list: an empty table and a failed request look identical to the reader,
  // and only one of them is true.
  private static async getPaginated(path: string, params: Record<string, unknown>): Promise<Paginated<any>> {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
    }
    const res = await fetch(`${API_BASE_URL}${path}?${query.toString()}`);
    if (!res.ok) {
      const detail = await res.json().catch(() => null);
      throw new Error(detail?.detail || `Request failed with status ${res.status}`);
    }
    return res.json();
  }

  public static getPages(
    sessionId: string,
    options: {
      offset?: number; limit?: number; sort?: string; order?: "asc" | "desc";
      filter?: string; status?: number; has_issues?: boolean;
    } = {},
  ): Promise<Paginated<any>> {
    return ApiService.getPaginated("/api/pages", { session_id: sessionId, ...options });
  }

  public static getIssues(
    sessionId: string,
    options: { offset?: number; limit?: number; severity?: string; code?: string } = {},
  ): Promise<Paginated<any>> {
    return ApiService.getPaginated("/api/issues", { session_id: sessionId, ...options });
  }

  public static getDuplicates(
    sessionId: string,
    options: { offset?: number; limit?: number } = {},
  ): Promise<Paginated<any> & { mode?: string }> {
    return ApiService.getPaginated("/api/duplicates", { session_id: sessionId, ...options });
  }

  public static async getArchitecture(sessionId: string, expand?: string): Promise<any> {
    const query = new URLSearchParams({ session_id: sessionId });
    if (expand) query.set("expand", expand);
    const res = await fetch(`${API_BASE_URL}/api/architecture?${query.toString()}`);
    if (!res.ok) return { clustered: true, nodes: [], links: [] };
    return res.json();
  }

  public static async getHistory(sessionId?: string): Promise<any> {
    const url = sessionId ? `${API_BASE_URL}/api/history?session_id=${sessionId}` : `${API_BASE_URL}/api/history`;
    const res = await fetch(url);
    if (!res.ok) return { sessions: [], comparison: null };
    return res.json();
  }

  
  public static async deleteHistory(sessionId: string): Promise<void> {
    const res = await fetch(`${API_BASE_URL}/api/history/${sessionId}`, { method: "DELETE" });
    if (!res.ok) throw new Error("Failed to delete session");
  }

  public static async getPageDetail(url: string, sessionId: string): Promise<any> {
    const res = await fetch(`${API_BASE_URL}/api/page/${encodeURIComponent(url)}?session_id=${sessionId}`);
    if (!res.ok) return null;
    return res.json();
  }

  public static async getInternalLinks(sessionId: string): Promise<any> {
    const res = await fetch(`${API_BASE_URL}/api/internal-links?session_id=${sessionId}`);
    if (!res.ok) return { site_wide_analysis: null, broken_links: [] };
    return res.json();
  }

  public static async downloadExport(fmt: string, sessionId: string): Promise<void> {
    const res = await fetch(`${API_BASE_URL}/api/export/${fmt}?session_id=${sessionId}`);
    if (!res.ok) {
      throw new Error(`Failed to download ${fmt} report`);
    }
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.style.display = "none";
    a.href = url;
    let filename = `audit_report.${fmt}`;
    const disposition = res.headers.get("content-disposition");
    if (disposition && disposition.indexOf("filename=") !== -1) {
      const matches = /filename="([^"]+)"/.exec(disposition);
      if (matches != null && matches[1]) filename = matches[1];
    }
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(a);
  }


  public static async getLatestAudit(sessionId: string): Promise<any> {
    const res = await fetch(`${API_BASE_URL}/api/audit/latest?session_id=${sessionId}`);
    if (!res.ok) throw new Error("Failed to fetch latest audit");
    return res.json();
  }

  public static async pauseAudit(sessionId: string): Promise<void> {
    await fetch(`${API_BASE_URL}/api/audit/pause?session_id=${sessionId}`, { method: "POST" });
  }

  public static async resumeAudit(sessionId: string): Promise<void> {
    await fetch(`${API_BASE_URL}/api/audit/resume?session_id=${sessionId}`, { method: "POST" });
  }

  public static async stopAudit(sessionId: string): Promise<void> {
    await fetch(`${API_BASE_URL}/api/audit/stop?session_id=${sessionId}`, { method: "POST" });
  }

  public static createWebSocketClient(

    onMessage: (event: MessageEvent) => void,
    onError?: (event: Event) => void
  ): WebSocket | null {
    if (typeof window === "undefined") return null;
    try {
      const ws = new WebSocket(WS_BASE_URL);
      ws.onmessage = onMessage;
      if (onError) ws.onerror = onError;
      return ws;
    } catch {
      return null;
    }
  }
}
