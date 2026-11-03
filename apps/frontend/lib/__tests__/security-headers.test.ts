import { describe, expect, it } from "vitest";

import { securityHeaders } from "@/lib/security-headers.mjs";

const asMap = (list: { key: string; value: string }[]) => Object.fromEntries(list.map((h) => [h.key, h.value]));

describe("security headers", () => {
  const h = asMap(securityHeaders({ apiUrl: "https://api.example.io/x", wsUrl: "wss://api.example.io/ws", dev: false }));

  it("sends the four headers the audit checks for", () => {
    expect(h["X-Content-Type-Options"]).toBe("nosniff");
    expect(h["X-Frame-Options"]).toBe("DENY");
    expect(h["Referrer-Policy"]).toBe("strict-origin-when-cross-origin");
    expect(h["Content-Security-Policy"]).toBeTruthy();
  });

  it("lets the page reach only itself and the backend", () => {
    const csp = h["Content-Security-Policy"];
    expect(csp).toContain("default-src 'self'");
    expect(csp).toContain("connect-src 'self' https://api.example.io wss://api.example.io");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("object-src 'none'");
    expect(csp).not.toContain("unsafe-eval");
  });

  it("allows eval only in development (Next's dev server needs it)", () => {
    const dev = asMap(securityHeaders({ apiUrl: "http://127.0.0.1:5000", wsUrl: "ws://localhost:5000/ws", dev: true }));
    expect(dev["Content-Security-Policy"]).toContain("'unsafe-eval'");
    expect(dev["Content-Security-Policy"]).toContain("connect-src 'self' http://127.0.0.1:5000 ws://localhost:5000");
  });

  it("ignores a missing or malformed URL instead of breaking the policy", () => {
    const csp = asMap(securityHeaders({ apiUrl: "", wsUrl: "not a url", dev: false }))["Content-Security-Policy"];
    expect(csp).toContain("connect-src 'self';");
  });
});
