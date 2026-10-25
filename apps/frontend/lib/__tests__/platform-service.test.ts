import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, Platform } from "@/services/platform";

function respond(status: number, body: unknown) {
  return vi.spyOn(global, "fetch").mockResolvedValue(
    new Response(body === undefined ? null : JSON.stringify(body), { status }),
  );
}

afterEach(() => vi.restoreAllMocks());

describe("Platform API client", () => {
  it("returns parsed JSON on success", async () => {
    respond(200, { items: [{ id: 1 }] });
    expect(await Platform.listProjects()).toEqual({ items: [{ id: 1 }] });
  });

  it("throws ApiError with FastAPI's detail", async () => {
    respond(429, { detail: "daily cap of 20 dataforseo_labs calls reached" });
    await expect(Platform.contentGap(1, {})).rejects.toMatchObject({
      status: 429, detail: "daily cap of 20 dataforseo_labs calls reached",
    });
  });

  it("reports an unreachable server as status 0", async () => {
    vi.spyOn(global, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    const error = await Platform.listProjects().catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(0);
  });

  it("handles 204 with no body", async () => {
    respond(204, undefined);
    await expect(Platform.deleteKeyword(3)).resolves.toBeUndefined();
  });

  it("sends JSON bodies and builds CSV links with repeated competitors", async () => {
    const fetchSpy = respond(200, { created: 1, skipped: 0 });
    await Platform.addKeywords(7, [{ phrase: "espresso", country: "GB", device: "mobile" }]);
    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/projects\/7\/keywords$/);
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({
      keywords: [{ phrase: "espresso", country: "GB", device: "mobile" }],
    });
    expect(Platform.contentGapCsvUrl(7, ["a.com", "b.org"])).toMatch(
      /\/api\/projects\/7\/content-gap\.csv\?country=US&language=en&limit=500&competitor=a\.com&competitor=b\.org$/,
    );
  });
});
