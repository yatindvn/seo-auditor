"""Command-line entry point.

    python -m app.cli https://example.com --max-pages 100 --out ./audit_output

Deliberately thin. The engine lives in app/; this module parses arguments, runs
one audit through the same pipeline the API uses, and writes the report files.

It holds no audit logic of its own. The previous CLI lived in a second copy of
the whole engine -- crawler, checks, analysis and the per-page loop -- which had
to be mirrored by hand (commit 8f18529) and policed by a parity test. Deleting
that copy removes the drift at its source.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from typing import List, Optional

from app.crawler.crawler import Crawler
from app.services import audit_service
from app.utils import report

OUTPUT_FILES = (
    "audit_report.json", "audit_report.xlsx", "audit_summary.pdf",
    "audit_report.html", "pages.csv",
)


def _progress(done: int, total: int, url: str) -> None:
    bar_len = 30
    filled = int(bar_len * done / max(total, 1))
    bar = "#" * filled + "-" * (bar_len - filled)
    short_url = url if len(url) < 70 else url[:67] + "..."
    print(f"\r[{bar}] {done}/{total}  {short_url:<70}", end="", flush=True)


def _parse_target_keywords(raw: Optional[str]) -> Optional[List[str]]:
    if not raw:
        return None
    keywords = [k.strip() for k in raw.split(",") if k.strip()]
    return keywords or None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Crawl a site and write a technical SEO audit report.",
    )
    p.add_argument("url", help="Start URL to crawl, e.g. https://example.com")
    p.add_argument("--max-pages", type=int, default=200, help="Maximum number of pages to crawl (default: 200)")
    p.add_argument("--max-depth", type=int, default=5, help="Maximum crawl depth (default: 5)")
    p.add_argument("--concurrency", type=int, default=8, help="Concurrent requests (default: 8)")
    p.add_argument("--timeout", type=int, default=15, help="Per-request timeout in seconds (default: 15)")
    p.add_argument("--retries", type=int, default=2, help="Retries per failed request (default: 2)")
    p.add_argument("--delay", type=float, default=0.0, help="Delay in seconds between requests per worker (politeness)")
    p.add_argument("--ignore-robots", action="store_true", help="Do not respect robots.txt disallow rules")
    p.add_argument("--skip-external-links", action="store_true", help="Skip checking external link status codes")
    p.add_argument("--max-external-links", type=int, default=100, help="Max external links to status-check")
    # Accepted and ignored: near-duplicate detection is unconditional since the
    # quadratic implementation was replaced (commit 8d29bcd), so opting in is
    # meaningless. Kept so existing scripts passing it do not break.
    p.add_argument("--check-near-duplicates", action="store_true",
                   help="Deprecated: near-duplicate detection always runs")
    p.add_argument("--psi-key", help="Google PageSpeed Insights API key for real Core Web Vitals data")
    p.add_argument("--psi-strategy", choices=["mobile", "desktop"], default="mobile", help="PSI strategy (default: mobile)")
    p.add_argument("--no-keyword-analysis", dest="enable_keyword_analysis", action="store_false", default=True,
                   help="Skip on-page keyword extraction")
    p.add_argument("--enable-keyword-suggestions", action="store_true", default=False,
                   help="Suggest keywords via Google Autocomplete (network calls)")
    p.add_argument("--enable-rank-check", action="store_true", default=False,
                   help="Check rankings via the Google Custom Search API (quota'd)")
    p.add_argument("--enable-competitor-gap", action="store_true", default=False,
                   help="Include competitor-gap keyword suggestions")
    p.add_argument("--target-keywords", default=None,
                   help="Comma-separated keywords to analyse instead of extracted ones")
    p.add_argument("--json", action="store_true", help="Output raw audit JSON result to stdout")
    p.add_argument("--out", default="./seo_audit_output", help="Output directory for reports (default: ./seo_audit_output)")
    return p


def _run_audit(args, progress_callback=None) -> dict:
    crawler = Crawler(
        start_url=args.url,
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        respect_robots=not args.ignore_robots,
        concurrency=args.concurrency,
        timeout=args.timeout,
        retries=args.retries,
        delay=args.delay,
    )
    return audit_service._build_audit_result(
        args.url,
        crawler,
        progress_callback=progress_callback,
        event_callback=None,
        enable_keyword_analysis=args.enable_keyword_analysis,
        enable_keyword_suggestions=args.enable_keyword_suggestions,
        enable_rank_check=args.enable_rank_check,
        enable_competitor_gap=args.enable_competitor_gap,
        target_keywords=_parse_target_keywords(args.target_keywords),
        external_link_check_limit=0 if args.skip_external_links else args.max_external_links,
        psi_key=args.psi_key,
        psi_strategy=args.psi_strategy,
    )


def _write_reports(out_dir: str, data: dict) -> None:
    os.makedirs(out_dir, exist_ok=True)
    exec_summary = data["executive_summary"]
    page_rows = data["pages"]

    report.export_json(os.path.join(out_dir, "audit_report.json"), data)
    report.export_csv(os.path.join(out_dir, "pages.csv"), page_rows)
    report.export_excel(os.path.join(out_dir, "audit_report.xlsx"), {
        "Executive Summary": [exec_summary["health_score"]],
        "Pages": page_rows,
        "Recommendations": data["recommendations"],
        "Broken Links": data["broken_links"],
        "Redirects": [
            {"start_url": c["start_url"], "hops": len(c["hops"]), "final_status": c["final_status"]}
            for c in data["redirects"]["redirect_chains"]
        ],
        "Duplicate Titles": [
            {"title": k, "pages": ", ".join(v)} for k, v in data["duplicates"]["duplicate_titles"].items()
        ],
        "Issue Frequency": data["issue_frequency"],
    })
    report.export_pdf_summary(os.path.join(out_dir, "audit_summary.pdf"), exec_summary)
    report.export_html_report(os.path.join(out_dir, "audit_report.html"), exec_summary, page_rows)


def _print_summary(data: dict, out_dir: str) -> None:
    exec_summary = data["executive_summary"]
    health = exec_summary["health_score"]
    print("\n" + "=" * 60)
    print(f"HEALTH SCORE: {health['score']}/100 (Grade {health['grade']})")
    print(f"Pages crawled: {exec_summary['pages_crawled']}")
    print(f"Critical issues: {health.get('critical_issues', 0)}  "
          f"Warnings: {health.get('warning_issues', 0)}  Info: {health.get('info_issues', 0)}")
    print(f"Orphan pages: {exec_summary['orphan_pages']}  Broken links: {exec_summary['broken_links']}")
    print("\nTop recommendations:")
    for i, rec in enumerate(data["recommendations"][:10], 1):
        print(f"  {i}. [{rec['severity'].upper()}] {rec['recommendation']} ({rec['affected_pages']} pages)")
    print("\nReports written to:", os.path.abspath(out_dir))
    for name in OUTPUT_FILES:
        print(f"  - {name}")
    print("=" * 60)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.json:
        # Machine-readable mode: the report goes to stdout and nothing else may,
        # so no progress bar and no summary.
        print(json.dumps(_run_audit(args)))
        return 0

    print(f"Starting SEO audit of {args.url}")
    print(f"  max_pages={args.max_pages}  max_depth={args.max_depth}  "
          f"concurrency={args.concurrency}  respect_robots={not args.ignore_robots}")
    started = time.time()

    data = _run_audit(args, progress_callback=_progress)

    print(f"\nCrawled {data['executive_summary']['pages_crawled']} pages in {time.time() - started:.1f}s")
    _write_reports(args.out, data)
    _print_summary(data, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
