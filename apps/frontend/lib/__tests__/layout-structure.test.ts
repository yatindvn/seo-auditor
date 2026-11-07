import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const read = (p: string) => readFileSync(resolve(__dirname, "../..", p), "utf-8");

// Keeps the audit code (provider, WebSocket client, API service) off pages that
// never run an audit: projects, keywords and content load less JavaScript.
describe("where the audit state lives", () => {
  it("is not in the root layout", () => {
    expect(read("app/layout.tsx")).not.toContain("AuditProvider");
  });
  it("wraps the homepage, dashboard and live crawl, which share it", () => {
    expect(read("app/(audit)/layout.tsx")).toContain("<AuditProvider>");
    for (const page of ["app/(audit)/(home)/page.tsx", "app/(audit)/dashboard/page.tsx", "app/(audit)/live-crawl/page.tsx"])
      expect(() => read(page)).not.toThrow();
  });
});
