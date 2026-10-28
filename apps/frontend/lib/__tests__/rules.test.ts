import { describe, expect, it } from "vitest";

import { buildRule, emptyForm, formFromRule, needsValue, opsFor } from "@/lib/rules";

describe("rule form helpers", () => {
  it("offers the operators that fit the chosen check", () => {
    expect(opsFor({ ...emptyForm(), type: "field", field: "title" }).map((o) => o.value)).toContain("starts_with");
    expect(opsFor({ ...emptyForm(), type: "field", field: "word_count" }).map((o) => o.value)).toEqual(["gte", "lte", "eq"]);
    expect(opsFor({ ...emptyForm(), type: "selector" }).map((o) => o.value)).toEqual(["exists", "not_exists", "count_eq", "count_gte", "count_lte"]);
    expect(opsFor({ ...emptyForm(), type: "text" }).map((o) => o.value)).toEqual(["contains", "not_contains"]);
  });

  it("knows which operators need a value", () => {
    expect(needsValue("is_empty")).toBe(false);
    expect(needsValue("exists")).toBe(false);
    expect(needsValue("contains")).toBe(true);
  });

  it("builds each kind of rule", () => {
    const base = { ...emptyForm(), name: "R", message: "", severity: "warning" as const, urlPattern: "" };
    expect(buildRule({ ...base, type: "field", field: "word_count", op: "gte", value: "300" })).toEqual({
      name: "R", severity: "warning", message: "", url_pattern: null,
      check: { type: "field", field: "word_count", op: "gte", value: 300 },
    });
    expect(buildRule({ ...base, type: "field", field: "title", op: "is_empty", value: "ignored" }).check)
      .toEqual({ type: "field", field: "title", op: "is_empty" });
    expect(buildRule({ ...base, type: "text", scope: "html", op: "contains", value: "gtag(", caseSensitive: true }).check)
      .toEqual({ type: "text", scope: "html", op: "contains", value: "gtag(", case_sensitive: true });
    expect(buildRule({ ...base, type: "selector", selector: ".price", op: "count_lte", value: "1", urlPattern: "/p/*" }))
      .toMatchObject({ url_pattern: "/p/*", check: { type: "selector", selector: ".price", op: "count_lte", value: 1 } });
  });

  it("round-trips a saved rule into the form", () => {
    const form = formFromRule({ id: 1, project_id: 2, name: "N", enabled: true, severity: "critical", message: "m",
      url_pattern: "/b/*", check: { type: "field", field: "title", op: "contains", value: "x" },
      description: "", created_at: "", updated_at: "" });
    expect(buildRule(form)).toEqual({ name: "N", severity: "critical", message: "m", url_pattern: "/b/*",
      check: { type: "field", field: "title", op: "contains", value: "x" } });
  });
});
