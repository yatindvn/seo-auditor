#!/usr/bin/env python3
"""
cli.py — SEO Auditor command-line entry point.

Usage:
    python -m seo_auditor.cli https://example.com --max-pages 100 --out ./audit_output

Or after packaging install: seo-audit https://example.com
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from types import SimpleNamespace

from . import checks, analysis, ai_suggestions, report, performance
from .crawler import Crawler
from .seo import keyword_extraction, rank_checker, keyword_suggestions


def _progress(done, total, url):
    bar_len = 30
    filled = int(bar_len * done / max(total, 1))
    bar = "#" * filled + "-" * (bar_len - filled)
    short_url = url if len(url) < 70 else url[:67] + "..."
    print(f"\r[{bar}] {done}/{total}  {short_url:<70}", end="", flush=True)


def _keyword_intel_config():
    """Reads the same 5 env vars as apps/backend/app/config/config.py — this
    tree has no dedicated config module, so this small helper keeps the two
    trees behaviorally identical without adding one."""
    return SimpleNamespace(
        GOOGLE_CSE_API_KEY=os.getenv("GOOGLE_CSE_API_KEY", ""),
        GOOGLE_CSE_CX=os.getenv("GOOGLE_CSE_CX", ""),
        GOOGLE_CSE_DAILY_QUOTA=int(os.getenv("GOOGLE_CSE_DAILY_QUOTA", "100")),
        GOOGLE_CSE_MAX_KEYWORDS_PER_PAGE=int(os.getenv("GOOGLE_CSE_MAX_KEYWORDS_PER_PAGE", "3")),
        GOOGLE_CSE_CACHE_TTL_HOURS=int(os.getenv("GOOGLE_CSE_CACHE_TTL_HOURS", "24")),
    )


def _resolve_keyword_data(target_keywords, enable_keyword_analysis, page_meta_entry, content_stats):
    """Decide what `keyword_data` should be for a page.

    `target_keywords` is an explicit manual override and always wins,
    regardless of `enable_keyword_analysis`. Otherwise, `enable_keyword_analysis`
    is the master switch for the whole feature: when False, extraction is
    skipped and an empty list is returned.
    """
    if target_keywords:
        return [{"phrase": k, "score": None, "found_in": []} for k in target_keywords]
    if not enable_keyword_analysis:
        return []
    return keyword_extraction.extract_keywords(page_meta_entry, content_stats)


def collect_audit_data(
    url,
    max_pages,
    max_depth,
    ignore_robots=False,
    concurrency=8,
    timeout=15,
    retries=2,
    delay=0.0,
    skip_external_links=False,
    max_external_links=100,
    check_near_duplicates=False,
    psi_key=None,
    psi_strategy="mobile",
    progress_callback=None,
    enable_keyword_analysis=True,
    enable_rank_check=False,
    enable_competitor_gap=False,
    target_keywords=None,
):
    """Run the full crawl + analysis pipeline and return the structured report dict.

    Shared by the CLI (`run_audit`) and the serverless API (`api/audit.py`) so both
    produce identical JSON without duplicating the audit logic and without writing
    any files to disk (important for read-only serverless filesystems).
    """
    crawler = Crawler(
        start_url=url,
        max_pages=max_pages,
        max_depth=max_depth,
        respect_robots=not ignore_robots,
        concurrency=concurrency,
        timeout=timeout,
        retries=retries,
        delay=delay,
        include_external_link_check=not skip_external_links,
    )

    crawler.crawl(progress_callback=progress_callback)

    if not skip_external_links:
        crawler.check_external_links(max_check=max_external_links)

    all_page_issues = {}
    page_meta = {}
    page_data_for_dupes = []
    psi_results = {}

    for page_url, page in crawler.results.items():
        issues = []
        issues += checks.check_status_and_https(page, {})
        issues += checks.check_mixed_content(page)
        canon_issues, canonical = checks.check_canonical(page, page_url)
        issues += canon_issues
        issues += checks.check_indexability(page)

        title_issues, title = checks.check_title(page)
        issues += title_issues
        desc_issues, desc = checks.check_meta_description(page)
        issues += desc_issues
        heading_issues, h1 = checks.check_headings(page)
        issues += heading_issues
        issues += checks.check_images(page)
        issues += checks.check_links(page)
        issues += checks.check_structured_data(page)
        issues += checks.check_open_graph_twitter(page)
        issues += checks.check_url_structure(page_url)

        content_issues, content_stats = checks.check_content(page)
        issues += content_issues

        issues += checks.check_mobile(page)
        issues += checks.check_accessibility(page)
        issues += checks.check_security_headers(page)
        issues += checks.check_hreflang(page)
        issues += checks.check_media(page)
        issues += checks.check_js_rendering_signal(page)

        weight = performance.analyze_page_weight(page)
        issues += performance.check_performance_proxies(page, weight)

        if psi_key and page.status_code == 200:
            psi_results[page_url] = performance.fetch_psi_metrics(page_url, psi_key, strategy=psi_strategy)

        # Extract Rich Page Signals (Phase 1)
        soup = checks._soup(page.html)
        meta_robots = None
        lang = None
        open_graph = {}
        twitter_cards = {}
        h2_count = 0
        h3_count = 0
        heading_hierarchy = []
        images_count = 0
        missing_alt_count = 0
        structured_data = []
        security_headers = {}

        if soup:
            html_el = soup.find("html")
            lang = html_el.get("lang") if html_el else None
            robots_tag = soup.find("meta", attrs={"name": "robots"})
            meta_robots = robots_tag.get("content") if robots_tag else None

            for meta_tag in soup.find_all("meta"):
                prop = meta_tag.get("property", "")
                name = meta_tag.get("name", "")
                content = meta_tag.get("content", "")
                if prop.startswith("og:"):
                    open_graph[prop] = content
                if name.startswith("twitter:"):
                    twitter_cards[name] = content

            h2s = soup.find_all("h2")
            h3s = soup.find_all("h3")
            h2_count = len(h2s)
            h3_count = len(h3s)

            for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
                text = h.get_text(strip=True)
                if text:
                    level = int(h.name[1])
                    heading_hierarchy.append({"level": level, "text": text[:100]})

            imgs = soup.find_all("img")
            images_count = len(imgs)
            missing_alt_count = sum(1 for img in imgs if not img.get("alt", "").strip())

            for script in soup.find_all("script", type="application/ld+json"):
                if script.string:
                    structured_data.append({"type": "JSON-LD", "raw": script.string.strip()[:500]})

        if page.headers:
            headers_lower = {k.lower(): v for k, v in page.headers.items()}
            for h in ("strict-transport-security", "content-security-policy", "x-frame-options", "x-content-type-options", "referrer-policy"):
                security_headers[h] = headers_lower.get(h, False)

        int_links = len(crawler.link_graph.get(page_url, set()))
        ext_links = len([u for u in crawler.external_links_checked if page_url in crawler.inbound_links.get(u, set())])
        word_cnt = content_stats.get("word_count", 0)

        all_page_issues[page_url] = issues
        page_meta[page_url] = {
            "title": title,
            "meta_description": desc,
            "h1": h1,
            "word_count": word_cnt,
            "canonical": canonical,
            "performance": weight,
            "meta_robots": meta_robots,
            "lang": lang,
            "open_graph": open_graph,
            "twitter_cards": twitter_cards,
            "h2_count": h2_count,
            "h3_count": h3_count,
            "heading_hierarchy": heading_hierarchy,
            "char_count": len(content_stats.get("text", "")),
            "reading_time_mins": max(1, round(word_cnt / 200)) if word_cnt else 0,
            "internal_links_count": int_links,
            "external_links_count": ext_links,
            "images_count": images_count,
            "missing_alt_count": missing_alt_count,
            "structured_data": structured_data,
            "security_headers": security_headers,
        }

        _kw_config = _keyword_intel_config()
        keyword_data = _resolve_keyword_data(
            target_keywords, enable_keyword_analysis, page_meta[page_url], content_stats
        )
        rank_data = (
            rank_checker.check_rankings(page_url, [k["phrase"] for k in keyword_data], _kw_config)
            if enable_rank_check else []
        )
        suggestions = (
            keyword_suggestions.suggest_keywords(
                keyword_data, page_meta[page_url], rank_data, _kw_config,
                fetch_page=crawler._fetch, page_url=page_url,
                enable_competitor_gap=enable_competitor_gap,
            )
            if enable_keyword_analysis else []
        )
        page_meta[page_url]["keyword_analysis"] = {
            "top_keywords": keyword_data,
            "rankings": rank_data,
            "suggested_keywords": suggestions,
        }

        page_data_for_dupes.append({
            "url": page_url,
            "title": title,
            "meta_description": desc,
            "h1": h1,
            "canonical": canonical,
            "content_hash": analysis.content_hash(content_stats["text"]) if content_stats["text"] else None,
            "text": content_stats["text"],
        })

    site_wide = analysis.build_link_graph_stats(crawler)
    duplicates = analysis.find_duplicates(page_data_for_dupes)
    near_dupes = analysis.near_duplicate_content(page_data_for_dupes) if check_near_duplicates else []
    redirects = analysis.redirect_report(crawler)
    broken_links = analysis.broken_link_report(crawler)

    recommendations = ai_suggestions.generate_recommendations(all_page_issues, site_wide)
    issue_freq = ai_suggestions.issue_frequency_summary(all_page_issues)

    exec_summary = report.build_executive_summary(
        crawler, all_page_issues, site_wide, duplicates, redirects, broken_links, recommendations
    )
    page_rows = report.build_page_level_report(crawler, all_page_issues, page_meta)

    # Site Architecture Nodes & Links (Phase 3 & Phase 5)
    arch_nodes = []
    arch_links = []
    orphan_set = set(site_wide.get("orphan_pages", []))
    dead_end_set = set(site_wide.get("dead_end_pages", []))
    broken_set = {b["url"] for b in broken_links}
    hub_set = {h[0] for h in site_wide.get("hub_pages_over_linked", [])}

    for url, res in crawler.results.items():
        arch_nodes.append({
            "id": url,
            "url": url,
            "label": url.replace("https://", "").replace("http://", "").split("?")[0],
            "depth": res.depth,
            "isBroken": url in broken_set or (res.status_code is not None and res.status_code >= 400),
            "isOrphan": url in orphan_set,
            "isDeadEnd": url in dead_end_set,
            "isDeep": res.depth >= 3,
            "isHub": url in hub_set,
            "inboundCount": len(crawler.inbound_links.get(url, set())),
            "outboundCount": len(crawler.link_graph.get(url, set())),
        })

    for src, targets in crawler.link_graph.items():
        for tgt in targets:
            if tgt in crawler.results:
                arch_links.append({"source": src, "target": tgt})

    return {
        "executive_summary": exec_summary,
        "site_wide_analysis": site_wide,
        "duplicates": duplicates,
        "near_duplicate_content": near_dupes,
        "redirects": redirects,
        "broken_links": broken_links,
        "recommendations": recommendations,
        "issue_frequency": issue_freq,
        "pages": page_rows,
        "architecture": {
            "nodes": arch_nodes,
            "links": arch_links,
        },
        "page_issues_detail": {u: v for u, v in all_page_issues.items()},
        "psi_metrics": psi_results,
        "robots_txt": crawler.robots_txt_content,
        "sitemaps_found": crawler.sitemaps_found,
    }


def run_audit(args) -> int:
    if getattr(args, "json", False):
        import json
        full_data = collect_audit_data(
            url=args.url,
            max_pages=args.max_pages,
            max_depth=args.max_depth,
            ignore_robots=args.ignore_robots,
            concurrency=args.concurrency,
            timeout=args.timeout,
            retries=args.retries,
            delay=args.delay,
            skip_external_links=args.skip_external_links,
            max_external_links=args.max_external_links,
            check_near_duplicates=args.check_near_duplicates,
            psi_key=args.psi_key,
            psi_strategy=args.psi_strategy,
            progress_callback=None,
        )
        print(json.dumps(full_data))
        return 0

    print(f"Starting SEO audit of {args.url}")
    print(f"  max_pages={args.max_pages}  max_depth={args.max_depth}  "
          f"respect_robots={not args.ignore_robots}  concurrency={args.concurrency}\n")

    t0 = time.time()
    full_data = collect_audit_data(
        url=args.url,
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        ignore_robots=args.ignore_robots,
        concurrency=args.concurrency,
        timeout=args.timeout,
        retries=args.retries,
        delay=args.delay,
        skip_external_links=args.skip_external_links,
        max_external_links=args.max_external_links,
        check_near_duplicates=args.check_near_duplicates,
        psi_key=args.psi_key,
        psi_strategy=args.psi_strategy,
        progress_callback=_progress,
    )

    exec_summary = full_data["executive_summary"]
    page_rows = full_data["pages"]
    recommendations = full_data["recommendations"]
    issue_freq = full_data["issue_frequency"]
    duplicates = full_data["duplicates"]
    redirects = full_data["redirects"]
    broken_links = full_data["broken_links"]

    print(f"\nCrawled {exec_summary['pages_crawled']} pages in {time.time() - t0:.1f}s")

    os.makedirs(args.out, exist_ok=True)

    json_path = os.path.join(args.out, "audit_report.json")
    report.export_json(json_path, full_data)

    csv_path = os.path.join(args.out, "pages.csv")
    report.export_csv(csv_path, page_rows)

    xlsx_path = os.path.join(args.out, "audit_report.xlsx")
    report.export_excel(xlsx_path, {
        "Executive Summary": [exec_summary["health_score"]],
        "Pages": page_rows,
        "Recommendations": recommendations,
        "Broken Links": broken_links,
        "Redirects": [
            {"start_url": c["start_url"], "hops": len(c["hops"]), "final_status": c["final_status"]}
            for c in redirects["redirect_chains"]
        ],
        "Duplicate Titles": [
            {"title": k, "pages": ", ".join(v)} for k, v in duplicates["duplicate_titles"].items()
        ],
        "Issue Frequency": issue_freq,
    })

    pdf_path = os.path.join(args.out, "audit_summary.pdf")
    report.export_pdf_summary(pdf_path, exec_summary)

    html_path = os.path.join(args.out, "audit_report.html")
    report.export_html_report(html_path, exec_summary, page_rows)

    print("\n" + "=" * 60)
    health = exec_summary["health_score"]
    print(f"HEALTH SCORE: {health['score']}/100 (Grade {health['grade']})")
    print(f"Pages crawled: {exec_summary['pages_crawled']}")
    print(f"Critical issues: {health.get('critical_issues', 0)}  "
          f"Warnings: {health.get('warning_issues', 0)}  Info: {health.get('info_issues', 0)}")
    print(f"Orphan pages: {exec_summary['orphan_pages']}  Broken links: {exec_summary['broken_links']}")
    print("\nTop recommendations:")
    for i, rec in enumerate(recommendations[:10], 1):
        print(f"  {i}. [{rec['severity'].upper()}] {rec['recommendation']} ({rec['affected_pages']} pages)")
    print("\nReports written to:", os.path.abspath(args.out))
    for f in ("audit_report.json", "audit_report.xlsx", "audit_summary.pdf", "audit_report.html", "pages.csv"):
        print(f"  - {f}")
    print("=" * 60)

    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="seo-audit",
        description="Full-site SEO auditor: crawls a website and produces technical, on-page, "
                     "content, performance, accessibility, and security SEO reports.",
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
    p.add_argument("--check-near-duplicates", action="store_true", help="Run near-duplicate content detection (O(n^2), slower)")
    p.add_argument("--psi-key", help="Google PageSpeed Insights API key for real Core Web Vitals data")
    p.add_argument("--psi-strategy", choices=["mobile", "desktop"], default="mobile", help="PSI strategy (default: mobile)")
    p.add_argument("--json", action="store_true", help="Output raw audit JSON result to stdout")
    p.add_argument("--out", default="./seo_audit_output", help="Output directory for reports (default: ./seo_audit_output)")
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.url.startswith(("http://", "https://")):
        args.url = "https://" + args.url
    try:
        return run_audit(args)
    except KeyboardInterrupt:
        print("\nAborted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
