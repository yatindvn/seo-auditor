import { NextRequest, NextResponse } from "next/server";
import { exec } from "child_process";
import { promisify } from "util";
import fs from "fs/promises";
import path from "path";
import os from "os";

const execAsync = promisify(exec);

async function runAuditLogic(url: string, maxPages: number, maxDepth: number, ignoreRobots: boolean) {
  // Try proxying to external backend if running (e.g. FastAPI serverless at port 8000 or production API)
  const backendUrl = process.env.SEO_AUDITOR_API_URL || "http://127.0.0.1:8000/api/audit";
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 3000);
    const resp = await fetch(backendUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        max_pages: maxPages,
        max_depth: maxDepth,
        ignore_robots: ignoreRobots,
      }),
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    if (resp.ok) {
      return await resp.json();
    }
  } catch {
    // Backend API not reachable directly, fallback to running python CLI directly
  }

  // Fallback: Run python crawler directly via python CLI
  const tempOutDir = await fs.mkdtemp(path.join(os.tmpdir(), "seo_audit_api_"));
  const pythonCmd = process.platform === "win32" ? "python" : "python3";
  // The `seo_auditor` Python package lives in the `seo_auditor/` backend folder,
  // so the CLI must be run from there for `python -m seo_auditor.cli` to resolve.
  const backendDir = path.join(process.cwd(), "seo_auditor");

  let cmd = `${pythonCmd} -m seo_auditor.cli "${url}" --max-pages ${maxPages} --max-depth ${maxDepth} --out "${tempOutDir}"`;
  if (ignoreRobots) {
    cmd += " --ignore-robots";
  }

  const startTime = Date.now();
  try {
    await execAsync(cmd, { cwd: backendDir });
    const jsonPath = path.join(tempOutDir, "audit_report.json");
    const rawData = await fs.readFile(jsonPath, "utf-8");
    const data = JSON.parse(rawData);
    const elapsed = Math.round((Date.now() - startTime) / 100) / 10;

    data.elapsed_seconds = elapsed;
    data.note = data.note || "Audit completed via serverless engine. Maximum 15 pages and 2 crawl depth enforced.";

    // Clean up temp directory
    try {
      await fs.rm(tempOutDir, { recursive: true, force: true });
    } catch {
      // ignore cleanup errors
    }

    return data;
  } catch (error: any) {
    // Clean up temp directory on failure
    try {
      await fs.rm(tempOutDir, { recursive: true, force: true });
    } catch {
      // ignore
    }
    throw new Error(error?.stderr || error?.message || "Failed to execute audit crawl");
  }
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    let { url, max_pages = 8, max_depth = 1, ignore_robots = false } = body || {};

    if (!url || typeof url !== "string") {
      return NextResponse.json({ detail: "URL is required" }, { status: 400 });
    }

    // Format URL
    let formattedUrl = url.trim();
    if (!formattedUrl.startsWith("http://") && !formattedUrl.startsWith("https://")) {
      formattedUrl = "https://" + formattedUrl;
    }

    // Enforce caps client/server-side
    const clampedPages = Math.min(Math.max(Number(max_pages) || 8, 1), 15);
    const clampedDepth = Math.min(Math.max(Number(max_depth) || 1, 0), 2);

    const result = await runAuditLogic(formattedUrl, clampedPages, clampedDepth, Boolean(ignore_robots));
    return NextResponse.json(result);
  } catch (err: any) {
    return NextResponse.json(
      { detail: err?.message || "An unexpected error occurred during the SEO audit." },
      { status: 500 }
    );
  }
}

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const url = searchParams.get("url");
  const max_pages = Number(searchParams.get("max_pages")) || 8;
  const max_depth = Number(searchParams.get("max_depth")) || 1;
  const ignore_robots = searchParams.get("ignore_robots") === "true";

  if (!url) {
    return NextResponse.json({ detail: "Query parameter 'url' is required" }, { status: 400 });
  }

  let formattedUrl = url.trim();
  if (!formattedUrl.startsWith("http://") && !formattedUrl.startsWith("https://")) {
    formattedUrl = "https://" + formattedUrl;
  }

  const clampedPages = Math.min(Math.max(max_pages, 1), 15);
  const clampedDepth = Math.min(Math.max(max_depth, 0), 2);

  try {
    const result = await runAuditLogic(formattedUrl, clampedPages, clampedDepth, ignore_robots);
    return NextResponse.json(result);
  } catch (err: any) {
    return NextResponse.json(
      { detail: err?.message || "An unexpected error occurred during the SEO audit." },
      { status: 500 }
    );
  }
}
