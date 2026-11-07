/** "Render JavaScript" asks the API to render a sample of pages for one audit. */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import LandingPage from "@/app/(audit)/(home)/page";
import { ApiService } from "@/services/api";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/lib/audit-context", () => ({
  useAudit: () => ({ startNewAudit: vi.fn(), setError: vi.fn(), isLoading: false, error: null }),
}));

async function submitWith(renderJs: boolean) {
  const runAudit = vi.spyOn(ApiService, "runAudit").mockResolvedValue({ session_id: "s" } as never);
  render(<LandingPage />);
  await userEvent.type(screen.getByPlaceholderText("https://example.com"), "https://example.com");
  await userEvent.click(screen.getByText("Advanced Overrides"));
  if (renderJs) await userEvent.click(screen.getByLabelText(/render javascript/i));
  await userEvent.click(screen.getByRole("button", { name: /start seo audit/i }));
  await waitFor(() => expect(runAudit).toHaveBeenCalled());
  return runAudit.mock.calls[0][0];
}

describe("Render JavaScript option", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("is off by default", async () => {
    expect(await submitWith(false)).toMatchObject({ render_js: false });
  });

  it("sends render_js when ticked", async () => {
    expect(await submitWith(true)).toMatchObject({ render_js: true });
  });
});
