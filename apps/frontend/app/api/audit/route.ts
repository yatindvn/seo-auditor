import { NextResponse } from "next/server";

// Proxies an audit request to the Python backend.
//
// There used to be a fallback for when no backend URL was set: build
// `python -m app.cli "${url}" ...` from the request body and exec it. That ran
// whatever a crafted `url` contained as a shell command on this host. The
// dashboard never calls this route -- it talks to the backend directly -- so
// the fallback is gone, not escaped: no request body ever reaches a shell.
export async function POST(req: Request) {
  const backendUrl = process.env.VITE_API_URL || process.env.NEXT_PUBLIC_API_URL;
  if (!backendUrl) {
    return NextResponse.json(
      { detail: "Backend URL is not configured. Set NEXT_PUBLIC_API_URL to the Python API." },
      { status: 503 },
    );
  }

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
