import { NextResponse } from "next/server";
import { exec } from "child_process";
import path from "path";
import util from "util";

const execAsync = util.promisify(exec);

export async function POST(req: Request) {
  const backendUrl = process.env.VITE_API_URL || process.env.NEXT_PUBLIC_API_URL;
  if (backendUrl) {
    try {
      const body = await req.json();
      const res = await fetch(`${backendUrl}/api/audit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      return NextResponse.json(data, { status: res.status });
    } catch (err: any) {
      return NextResponse.json({ detail: err.message || "Failed to reach backend server" }, { status: 500 });
    }
  }

  // Fallback direct execution via backend Python engine if backend server URL isn't set
  try {
    const body = await req.json();
    const { url, max_pages = 8, max_depth = 1, ignore_robots = false } = body;
    if (!url) {
      return NextResponse.json({ detail: "URL is required" }, { status: 400 });
    }

    const scriptPath = path.resolve(process.cwd(), "../backend/seo_auditor");
    const cmd = `python -m seo_auditor.cli "${url}" --max-pages ${max_pages} --max-depth ${max_depth} ${ignore_robots ? "--ignore-robots" : ""} --json`;
    const { stdout } = await execAsync(cmd, { cwd: scriptPath });
    const result = JSON.parse(stdout);
    return NextResponse.json(result);
  } catch (err: any) {
    return NextResponse.json({ detail: err.message || "Audit execution failed" }, { status: 500 });
  }
}
