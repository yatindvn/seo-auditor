"""Measure a real crawl against a synthetic site.

Run manually, not in CI: wall-clock numbers from shared CI runners are noise, but
a regression here is the whole point of the pipeline work, so the harness is
committed and the ceilings are explicit.

    cd apps/backend
    python perf/crawl_harness.py                 # 1000 pages
    python perf/crawl_harness.py --pages 5000    # the Full Site Crawl preset

It serves a site of interlinked pages from a background HTTP server, runs one
audit through the real pipeline, and reports wall clock and peak memory against
the budget in docs/superpowers/specs/2026-09-26-full-site-crawl-scale-design.md.

Exits non-zero when a ceiling is breached, so it can gate a release by hand.
"""

from __future__ import annotations

import argparse
import http.server
import os
import socketserver
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.crawler.crawler import Crawler  # noqa: E402
from app.services import audit_service  # noqa: E402

# From the spec's performance budget, for the documented 2 OCPU / 12 GB shape.
# Scaled by page count so a 1000-page run is a meaningful proxy for 5000.
SECONDS_PER_1000_PAGES = 180
PEAK_RSS_CEILING_MB = 1536

# Words per page, chosen so the pages are neither trivially short nor
# unrepresentatively long: signature cost scales with this.
WORDS_PER_PAGE = 600


def _page_html(index: int, total: int, links_per_page: int = 12) -> bytes:
    """A page with a title, headings, body text and outbound links.

    Deliberately not identical across pages: identical bodies would collapse
    into one duplicate cluster and make the duplicate pass unrealistically
    cheap, which is one of the things being measured.
    """
    targets = [(index * 7 + offset + 1) % total for offset in range(links_per_page)]
    links = "".join(f'<a href="/page{target}.html">link {target}</a>' for target in targets)
    words = " ".join(
        f"word{(index * 31 + position) % 5000}" for position in range(WORDS_PER_PAGE)
    )
    return (
        f"<html lang='en'><head><title>Page {index} of the synthetic site</title>"
        f"<meta name='description' content='Synthetic page {index} for measurement'>"
        f"</head><body><h1>Heading for page {index}</h1><h2>Subheading</h2>"
        f"<p>{words}</p><img src='/img{index}.png' alt='an image'>"
        f"<img src='/noalt{index}.png'>{links}</body></html>"
    ).encode("utf-8")


class _SiteHandler(http.server.BaseHTTPRequestHandler):
    total_pages = 1000

    def do_GET(self):  # noqa: N802 - name fixed by BaseHTTPRequestHandler
        if self.path in ("/", "/index.html"):
            body = _page_html(0, self.total_pages)
        elif self.path.startswith("/page") and self.path.endswith(".html"):
            try:
                index = int(self.path[len("/page"):-len(".html")])
            except ValueError:
                self.send_error(404)
                return
            body = _page_html(index, self.total_pages)
        elif self.path == "/robots.txt":
            self.send_response(404)
            self.end_headers()
            return
        else:
            self.send_error(404)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        """Silence per-request logging: 5000 lines of it would dominate the
        output and cost measurable time."""


def _peak_rss_mb() -> float | None:
    """Peak resident memory, or None where the platform will not say.

    resource.getrusage is POSIX-only; psutil gives current rather than peak, so
    it is sampled instead. A missing number is reported as missing rather than
    guessed.
    """
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux reports kilobytes, macOS bytes.
        return peak / 1024 if sys.platform != "darwin" else peak / (1024 * 1024)
    except ImportError:
        pass

    if sys.platform == "win32":
        # Windows has no getrusage. PeakWorkingSetSize is the same measure and
        # needs no third-party package, which matters: an unmeasured ceiling is
        # a ceiling nobody is checking.
        import ctypes
        from ctypes import wintypes

        class _MemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = _MemoryCounters()
        counters.cb = ctypes.sizeof(_MemoryCounters)
        # Both signatures have to be declared. Left to ctypes' defaults the
        # handle comes back as a 32-bit int, which truncates on 64-bit Windows
        # and the call fails silently -- an unmeasured ceiling nobody notices.
        kernel32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(_MemoryCounters), wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        if psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        ):
            return counters.PeakWorkingSetSize / (1024 * 1024)
        return None

    try:
        import psutil

        return psutil.Process().memory_info().rss / (1024 * 1024)
    except ImportError:
        return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=int, default=1000)
    parser.add_argument("--port", type=int, default=8977)
    parser.add_argument("--depth", type=int, default=15)
    # The deployed shape has 2 OCPUs. A development machine usually has many
    # more, which makes the CPU-bound stage look far faster than production, so
    # the pool width is settable and the default matches the VM.
    parser.add_argument("--workers", type=int, default=2,
                        help="process pool width (default 2, the deployed shape)")
    args = parser.parse_args(argv)

    _SiteHandler.total_pages = args.pages
    socketserver.TCPServer.allow_reuse_address = True
    server = socketserver.ThreadingTCPServer(("127.0.0.1", args.port), _SiteHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    start_url = f"http://127.0.0.1:{args.port}/"
    print(f"Serving {args.pages} synthetic pages at {start_url}")

    crawler = Crawler(
        start_url=start_url,
        max_pages=args.pages,
        max_depth=args.depth,
        respect_robots=False,
    )

    print(f"analysis pool width {args.workers} (this machine has {os.cpu_count()} cores)")

    started = time.monotonic()
    original_cpu_count = os.cpu_count
    os.cpu_count = lambda: args.workers  # type: ignore[assignment]
    try:
        result = audit_service._build_audit_result(
            start_url, crawler, progress_callback=None, event_callback=None,
            external_link_check_limit=0,
            session_id=f"perf_{int(time.time())}",
        )
    finally:
        os.cpu_count = original_cpu_count  # type: ignore[assignment]
        server.shutdown()
        server.server_close()
    elapsed = time.monotonic() - started

    budget = SECONDS_PER_1000_PAGES * args.pages / 1000
    peak_mb = _peak_rss_mb()
    crawled = result["executive_summary"]["pages_crawled"]

    print()
    print(f"pages crawled       {crawled}")
    print(f"wall clock          {elapsed:.1f}s   (budget {budget:.0f}s)")
    print(f"per page            {elapsed / max(crawled, 1) * 1000:.1f}ms")
    print(f"peak RSS            {f'{peak_mb:.0f}MB' if peak_mb else 'unavailable on this platform'}"
          f"   (ceiling {PEAK_RSS_CEILING_MB}MB)")
    print(f"duplicate mode      {result['near_duplicate_mode']}")
    print(f"degraded            {result['degraded']}")

    failures = []
    if elapsed > budget:
        failures.append(f"wall clock {elapsed:.1f}s exceeds the {budget:.0f}s budget")
    if peak_mb and peak_mb > PEAK_RSS_CEILING_MB:
        failures.append(f"peak RSS {peak_mb:.0f}MB exceeds the {PEAK_RSS_CEILING_MB}MB ceiling")
    if crawled < args.pages * 0.95:
        failures.append(f"only {crawled} of {args.pages} pages were crawled")

    print()
    if failures:
        for failure in failures:
            print(f"OVER BUDGET: {failure}")
        # The lever is per-page check cost, not more workers: the deployed shape
        # has 2 OCPUs. The metadata block in page_pipeline walks the parsed tree
        # several times and can be folded into one pass.
        print("Reduce per-page check cost before adding workers.")
        return 1

    print("within budget")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
