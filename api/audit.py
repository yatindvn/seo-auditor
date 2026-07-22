"""
Vercel Python Serverless Function — POST /api/audit

Runs the SEO crawl + analysis pipeline in-memory and returns the full JSON
report. This replaces the old Node route that shell-executed the Python CLI
(which cannot work on Vercel's Node serverless runtime).

The heavy `seo_auditor` package lives in `<repo>/seo_auditor/seo_auditor`. We add
that directory to sys.path so it can be imported here. `vercel.json` bundles the
package files into this function via `includeFiles`.
"""

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Make the `seo_auditor` package importable (it lives one level up under seo_auditor/).
_PACKAGE_PARENT = os.path.join(os.path.dirname(__file__), "..", "seo_auditor")
if _PACKAGE_PARENT not in sys.path:
    sys.path.insert(0, _PACKAGE_PARENT)

# Serverless caps — keep crawls small enough to finish within the function timeout.
MAX_PAGES_CAP = 15
MAX_DEPTH_CAP = 2


def _clamp(value, default, low, high):
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(low, min(n, high))


def _normalize_url(url):
    url = (url or "").strip()
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _run_audit(url, max_pages, max_depth, ignore_robots):
    # Imported lazily so import errors surface as a clean 500 rather than at cold start.
    from seo_auditor.cli import collect_audit_data

    started = time.time()
    data = collect_audit_data(
        url=url,
        max_pages=_clamp(max_pages, 8, 1, MAX_PAGES_CAP),
        max_depth=_clamp(max_depth, 1, 0, MAX_DEPTH_CAP),
        ignore_robots=bool(ignore_robots),
        # Tuned for a short-lived serverless invocation.
        concurrency=10,
        timeout=10,
        retries=1,
        skip_external_links=False,
        max_external_links=25,
        check_near_duplicates=False,
    )
    data["elapsed_seconds"] = round(time.time() - started, 1)
    data["note"] = (
        f"Audit completed via serverless engine. Maximum {MAX_PAGES_CAP} pages "
        f"and {MAX_DEPTH_CAP} crawl depth enforced."
    )
    return data


class handler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _handle(self, url, max_pages, max_depth, ignore_robots):
        url = _normalize_url(url)
        if not url:
            self._send_json(400, {"detail": "URL is required"})
            return
        try:
            self._send_json(200, _run_audit(url, max_pages, max_depth, ignore_robots))
        except Exception as exc:  # noqa: BLE001 - surface any crawl failure to the client
            self._send_json(500, {"detail": str(exc) or "An unexpected error occurred during the SEO audit."})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._send_json(400, {"detail": "Invalid JSON body"})
            return
        self._handle(
            body.get("url"),
            body.get("max_pages", 8),
            body.get("max_depth", 1),
            body.get("ignore_robots", False),
        )

    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        if "url" not in params:
            self._send_json(400, {"detail": "Query parameter 'url' is required"})
            return
        self._handle(
            params.get("url", [None])[0],
            params.get("max_pages", ["8"])[0],
            params.get("max_depth", ["1"])[0],
            params.get("ignore_robots", ["false"])[0] == "true",
        )
