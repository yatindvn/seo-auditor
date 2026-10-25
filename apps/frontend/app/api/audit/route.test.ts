// @vitest-environment node
/**
 * POST /api/audit on the Next.js server only ever proxies to the backend.
 *
 * It used to fall back, when no backend URL was configured, to building a shell
 * command from the request body and running it -- so a `url` containing `"` or
 * `$(...)` ran arbitrary commands on the host. The dashboard never called this
 * route (it talks to the backend directly), so the fallback is removed rather
 * than escaped.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const exec = vi.fn();
vi.mock("child_process", () => ({ exec, default: { exec } }));

const ENV_KEYS = ["NEXT_PUBLIC_API_URL", "VITE_API_URL"] as const;
let saved: Record<string, string | undefined> = {};

function auditRequest(body: unknown) {
  return new Request("http://localhost/api/audit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function loadRoute() {
  vi.resetModules();
  return import("./route");
}

describe("POST /api/audit", () => {
  beforeEach(() => {
    saved = Object.fromEntries(ENV_KEYS.map((key) => [key, process.env[key]]));
    ENV_KEYS.forEach((key) => delete process.env[key]);
    exec.mockReset();
  });

  afterEach(() => {
    ENV_KEYS.forEach((key) => {
      if (saved[key] === undefined) delete process.env[key];
      else process.env[key] = saved[key];
    });
    vi.unstubAllGlobals();
  });

  it("never runs a shell command, whatever the url contains", async () => {
    const { POST } = await loadRoute();

    const response = await POST(auditRequest({ url: 'https://example.com"; touch /tmp/pwned; "' }));

    expect(exec).not.toHaveBeenCalled();
    expect(response.status).toBe(503);
  });

  it("says the backend is not configured instead of auditing locally", async () => {
    const { POST } = await loadRoute();

    const response = await POST(auditRequest({ url: "https://example.com" }));

    expect(await response.json()).toEqual({
      detail: expect.stringMatching(/NEXT_PUBLIC_API_URL/),
    });
  });

  it("still proxies to the backend when one is configured", async () => {
    process.env.NEXT_PUBLIC_API_URL = "http://backend.test";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "started", session_id: "s1" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { POST } = await loadRoute();

    const response = await POST(auditRequest({ url: "https://example.com" }));

    expect(fetchMock).toHaveBeenCalledWith("http://backend.test/api/audit", expect.objectContaining({ method: "POST" }));
    expect(await response.json()).toEqual({ status: "started", session_id: "s1" });
    expect(exec).not.toHaveBeenCalled();
  });
});
