import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import RulesPage from "@/app/projects/[id]/rules/page";
import { Platform } from "@/services/platform";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }), usePathname: () => "/projects/7/rules" }));

const rule = {
  id: 3, project_id: 7, name: "Brand in title", enabled: true, severity: "warning" as const, message: "",
  url_pattern: "/blog/*", check: { type: "field" as const, field: "title", op: "contains", value: "| Brand" },
  description: "Title contains '| Brand'", created_at: "", updated_at: "",
};

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(Platform, "listAudits").mockResolvedValue({ items: [{ id: 11 }], total: 1, offset: 0, limit: 1 } as any);
  vi.spyOn(Platform, "auditCustomRules").mockResolvedValue({ audit_id: 11, items: [
    { rule_id: 3, name: "Brand in title", severity: "warning", description: "", pages_checked: 20, pages_failed: 3, example_urls: [] }] });
});

describe("Custom Rules tab", () => {
  it("lists rules with their description, scope, severity and last result", async () => {
    vi.spyOn(Platform, "listRules").mockResolvedValue({ items: [rule] });
    render(<RulesPage params={{ id: "7" }} />);
    expect(await screen.findByText("Brand in title")).toBeInTheDocument();
    expect(screen.getByText("Title contains '| Brand'")).toBeInTheDocument();
    expect(screen.getByText("/blog/*")).toBeInTheDocument();
    expect(screen.getByText("Warning")).toBeInTheDocument();
    expect(await screen.findByText(/failed on 3 of 20 pages/i)).toBeInTheDocument();
  });

  it("toggles and deletes a rule", async () => {
    vi.spyOn(Platform, "listRules").mockResolvedValue({ items: [rule] });
    const update = vi.spyOn(Platform, "updateRule").mockResolvedValue({ ...rule, enabled: false });
    const remove = vi.spyOn(Platform, "deleteRule").mockResolvedValue(undefined);
    render(<RulesPage params={{ id: "7" }} />);
    await userEvent.click(await screen.findByRole("switch", { name: /enable brand in title/i }));
    expect(update).toHaveBeenCalledWith(3, { enabled: false });
    await userEvent.click(screen.getByRole("button", { name: /delete brand in title/i }));
    await userEvent.click(screen.getByRole("button", { name: /confirm delete/i }));
    expect(remove).toHaveBeenCalledWith(3);
  });

  it("builds a selector rule, tests it on a URL, and saves it", async () => {
    vi.spyOn(Platform, "listRules").mockResolvedValue({ items: [] });
    const test = vi.spyOn(Platform, "testRule").mockResolvedValue({ applies: true, passed: false, observed: 0, issue: null });
    const create = vi.spyOn(Platform, "createRule").mockResolvedValue({ ...rule, id: 9 });
    render(<RulesPage params={{ id: "7" }} />);
    await userEvent.click(await screen.findByRole("button", { name: /new rule/i }));
    await userEvent.type(screen.getByLabelText(/^name/i), "Has JSON-LD");
    await userEvent.selectOptions(screen.getByLabelText(/check/i), "selector");
    // paste, not type: userEvent.type reads "[" as a key descriptor.
    await userEvent.click(screen.getByLabelText(/css selector/i));
    await userEvent.paste("script[type='application/ld+json']");
    await userEvent.selectOptions(screen.getByLabelText(/condition/i), "exists");
    expect(screen.queryByLabelText(/^value/i)).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/test on a url/i), "https://shop.com/p");
    await userEvent.click(screen.getByRole("button", { name: /^test$/i }));
    expect(await screen.findByText(/failed/i)).toBeInTheDocument();
    expect(screen.getByText(/saw: 0/i)).toBeInTheDocument();
    expect(test.mock.calls[0][1]).toBe("https://shop.com/p");
    await userEvent.click(screen.getByRole("button", { name: /save rule/i }));
    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(create.mock.calls[0][1]).toEqual({ name: "Has JSON-LD", severity: "warning", message: "", url_pattern: null,
      check: { type: "selector", selector: "script[type='application/ld+json']", op: "exists" } });
  });

  it("shows a save error from the server", async () => {
    vi.spyOn(Platform, "listRules").mockResolvedValue({ items: [] });
    const { ApiError } = await import("@/services/platform");
    vi.spyOn(Platform, "createRule").mockRejectedValue(new ApiError(422, "check: Invalid CSS selector: bad"));
    render(<RulesPage params={{ id: "7" }} />);
    await userEvent.click(await screen.findByRole("button", { name: /new rule/i }));
    await userEvent.type(screen.getByLabelText(/^name/i), "X");
    await userEvent.type(screen.getByLabelText(/^value/i), "abc");
    await userEvent.click(screen.getByRole("button", { name: /save rule/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid CSS selector");
  });

  it("offers an example rule when there are none", async () => {
    vi.spyOn(Platform, "listRules").mockResolvedValue({ items: [] });
    const create = vi.spyOn(Platform, "createRule").mockResolvedValue(rule);
    render(<RulesPage params={{ id: "7" }} />);
    await userEvent.click(await screen.findByRole("button", { name: /add an example rule/i }));
    expect(create.mock.calls[0][1].check).toEqual({ type: "field", field: "title", op: "is_not_empty" });
  });
});
