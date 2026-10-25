/**
 * "Re-check every page" asks the API to ignore its page cache for one audit.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import LandingPage from "@/app/page";
import { ApiService } from "@/services/api";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/audit-context", () => ({
  useAudit: () => ({
    startNewAudit: vi.fn(),
    setError: vi.fn(),
    isLoading: false,
    error: null,
  }),
}));

async function submitWith(recheck: boolean) {
  const runAudit = vi.spyOn(ApiService, "runAudit").mockResolvedValue({ session_id: "s" } as never);
  render(<LandingPage />);

  await userEvent.type(screen.getByPlaceholderText("https://example.com"), "https://example.com");
  await userEvent.click(screen.getByText("Advanced Overrides"));
  if (recheck) {
    await userEvent.click(screen.getByLabelText(/re-check every page/i));
  }
  await userEvent.click(screen.getByRole("button", { name: /start seo audit/i }));

  await waitFor(() => expect(runAudit).toHaveBeenCalled());
  return runAudit.mock.calls[0][0];
}

describe("Re-check every page", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("is off by default, so unchanged pages are reused", async () => {
    expect(await submitWith(false)).toMatchObject({ fresh: false });
  });

  it("sends fresh when ticked", async () => {
    expect(await submitWith(true)).toMatchObject({ fresh: true });
  });
});
