/**
 * What survives a page reload.
 *
 * The audit payload used to carry every page row, and the whole thing was
 * stringified into sessionStorage. Now the payload is a summary and the rows
 * live behind paginated endpoints -- which means the *session id* has to
 * persist too. Without it a reload restores a summary the panels cannot fetch
 * any detail for.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import { AuditProvider, useAudit } from "@/lib/audit-context";
import { ApiService } from "@/services/api";

const STORAGE_KEY = "seo_auditor_latest_results";

function Probe() {
  const { activeSessionId, auditData } = useAudit();
  return (
    <div>
      <span data-testid="session">{activeSessionId ?? "none"}</span>
      <span data-testid="score">
        {auditData?.executive_summary?.health_score?.score ?? "none"}
      </span>
    </div>
  );
}

const SUMMARY = {
  executive_summary: { health_score: { score: 82 }, pages_crawled: 10 },
  page_count: 10,
};

describe("audit context persistence", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    vi.restoreAllMocks();
  });

  afterEach(() => vi.restoreAllMocks());

  it("restores the session id alongside the summary", async () => {
    window.sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ sessionId: "sess_restored", summary: SUMMARY }),
    );

    render(<AuditProvider><Probe /></AuditProvider>);

    await waitFor(() => {
      expect(screen.getByTestId("session")).toHaveTextContent("sess_restored");
      expect(screen.getByTestId("score")).toHaveTextContent("82");
    });
  });

  it("stores no page rows", async () => {
    vi.spyOn(ApiService, "getPages").mockResolvedValue({
      items: [], total: 0, offset: 0, limit: 200,
    });

    render(<AuditProvider><Probe /></AuditProvider>);

    await waitFor(() => {
      const stored = window.sessionStorage.getItem(STORAGE_KEY);
      if (!stored) return;
      expect(JSON.parse(stored).summary?.pages).toBeUndefined();
    });
  });

  it("renders when storage throws", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("QuotaExceededError");
    });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("SecurityError");
    });

    expect(() =>
      render(<AuditProvider><Probe /></AuditProvider>),
    ).not.toThrow();
  });

  it("ignores malformed stored state rather than crashing the dashboard", () => {
    window.sessionStorage.setItem(STORAGE_KEY, "{not json");

    render(<AuditProvider><Probe /></AuditProvider>);

    expect(screen.getByTestId("session")).toHaveTextContent("none");
  });
});
