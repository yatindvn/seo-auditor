import { AuditRequestParams } from "../types";

export function validateAuditRequest(input: any): { valid: boolean; error?: string; data?: AuditRequestParams } {
  if (!input || typeof input !== "object") {
    return { valid: false, error: "Invalid request payload" };
  }
  const url = typeof input.url === "string" ? input.url.trim() : "";
  if (!url) {
    return { valid: false, error: "URL is required" };
  }
  const max_pages = typeof input.max_pages === "number" ? Math.max(1, Math.min(input.max_pages, 50)) : 8;
  const max_depth = typeof input.max_depth === "number" ? Math.max(0, Math.min(input.max_depth, 5)) : 1;
  const ignore_robots = Boolean(input.ignore_robots);

  return {
    valid: true,
    data: {
      url,
      max_pages,
      max_depth,
      ignore_robots,
    },
  };
}
