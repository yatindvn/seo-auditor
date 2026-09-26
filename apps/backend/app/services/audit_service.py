import logging
import time
import asyncio
from typing import Any, Dict, List, Optional
from app.crawler.crawler import Crawler
from app.auditor import checks
from app.analysis import analysis
from app.ai import ai_suggestions
from app.utils import performance, report
from app.models.session_model import session_store
from app.websocket.ws_manager import ws_manager
from app.config import config
from app.seo import rank_checker, keyword_suggestions
from app.services import page_pipeline

# Same logger name the API layer uses (app/api/routes.py), so audit failures and
# crawl failures land in one stream rather than two.
logger = logging.getLogger("seo_auditor")


# Crawlers currently running, keyed by session_id — each pause/resume/stop
# request must only ever affect the crawl that session actually started.
active_crawlers: Dict[str, Any] = {}


def register_crawler(session_id: str, crawler: Any) -> None:
    active_crawlers[session_id] = crawler


def unregister_crawler(session_id: str) -> None:
    active_crawlers.pop(session_id, None)


def get_crawler(session_id: str) -> Optional[Any]:
    return active_crawlers.get(session_id)


def _match_rank_target(page_url: str, rank_targets: Optional[List[Any]]) -> Optional[List[str]]:
    """Return the nominated keywords for `page_url`, or None if not nominated.

    Both sides are normalised with rank_checker._normalize_url, which strips
    scheme, leading www., query string, fragment, and trailing slash — so a user
    typing "example.com/services" matches the crawled
    "https://www.example.com/services/".
    """
    if not rank_targets:
        return None
    normalized_page = rank_checker._normalize_url(page_url)
    for target in rank_targets:
        if rank_checker._normalize_url(target.url) == normalized_page:
            return list(target.keywords)
    return None


def run_full_audit(
    url: str,
    session_id: str,
    max_pages: int = 15,
    max_depth: int = 2,
    ignore_robots: bool = False,
    progress_callback=None,
    event_callback=None,
    enable_keyword_analysis: bool = True,
    enable_keyword_suggestions: bool = False,
    enable_rank_check: bool = False,
    enable_competitor_gap: bool = False,
    target_keywords: Optional[List[str]] = None,
    rank_targets: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    crawler = Crawler(
        start_url=url,
        max_pages=max_pages,
        max_depth=max_depth,
        respect_robots=not ignore_robots,
        concurrency=config.CRAWL_CONCURRENCY,
        timeout=10,
        retries=1,
    )

    register_crawler(session_id, crawler)
    try:
        return _build_audit_result(
            url, crawler, progress_callback, event_callback,
            enable_keyword_analysis, enable_keyword_suggestions, enable_rank_check,
            enable_competitor_gap, target_keywords, rank_targets=rank_targets,
        )
    finally:
        unregister_crawler(session_id)


def _build_audit_result(
    url: str,
    crawler: Crawler,
    progress_callback,
    event_callback,
    enable_keyword_analysis: bool = True,
    enable_keyword_suggestions: bool = False,
    enable_rank_check: bool = False,
    enable_competitor_gap: bool = False,
    target_keywords: Optional[List[str]] = None,
    rank_targets: Optional[List[Any]] = None,
    external_link_check_limit: int = 25,
    psi_key: Optional[str] = None,
    psi_strategy: str = "mobile",
) -> Dict[str, Any]:
    # Monotonic, not time.time(): this is a duration, and monotonic cannot be
    # skewed by an NTP correction or a manual clock change mid-audit.
    started_at = time.monotonic()

    crawler.crawl(progress_callback=progress_callback, event_callback=event_callback)
    # 0 means skip the requests entirely (the CLI's --skip-external-links), not
    # issue zero-length ones. 25 is the API's long-standing default.
    if external_link_check_limit:
        crawler.check_external_links(max_check=external_link_check_limit)

    all_page_issues = {}
    page_meta = {}
    page_data_for_dupes = []
    psi_results: Dict[str, Any] = {}
    signatures: Dict[str, bytes] = {}
    # Decided from the page cap, not the realised count: each page is signed (or
    # not) as it is analysed, long before the crawl's final size is known.
    # getattr because the cap is a Crawler attribute and callers may pass any
    # object exposing crawler.results.
    compute_signature = getattr(crawler, "max_pages", 0) > analysis.EXACT_PATH_MAX_PAGES

    for page_url, page in crawler.results.items():
        # Everything that happens to one page's HTML now lives in a pure,
        # picklable function, so it can run in a process pool alongside the
        # crawl instead of as a phase appended to it. What stays here is what
        # must not be multiplied across worker processes: the quota'd Google
        # APIs and PageSpeed Insights.
        #
        # The boundary is unchanged in spirit from the inline version: one
        # page's failure must not discard a crawl that has already been paid
        # for, and the page says so rather than going quietly blank.
        try:
            analysis_result = page_pipeline.analyze_page(page_pipeline.PagePayload(
                url=page_url,
                final_url=page.final_url,
                status_code=page.status_code,
                headers=page.headers,
                html=page.html,
                depth=page.depth,
                redirect_chain=page.redirect_chain,
                response_time_ms=page.response_time_ms,
                content_type=page.content_type,
                error=page.error,
                enable_keyword_analysis=enable_keyword_analysis,
                target_keywords=target_keywords,
                compute_signature=compute_signature,
            ))
        except Exception as exc:
            logger.error("Audit checks failed for %s: %s", page_url, exc, exc_info=exc)
            failed = page_pipeline.failed_analysis(page_url, exc)
            all_page_issues[page_url] = failed.issues
            page_meta[page_url] = failed.meta
            continue

        all_page_issues[page_url] = analysis_result.issues
        page_meta[page_url] = analysis_result.meta
        if analysis_result.signature:
            signatures[page_url] = analysis_result.signature
        keyword_data = analysis_result.keyword_data

        # PageSpeed Insights is a quota'd Google API and a per-page network
        # round trip, so it runs only when a key is supplied -- never by
        # default, and never for a page that did not return 200.
        if psi_key and page.status_code == 200:
            psi_results[page_url] = performance.fetch_psi_metrics(
                page_url, psi_key, strategy=psi_strategy
            )

        # Rank checks fire only on pages the user nominated. With enable_rank_check
        # on but nothing nominated, spend is zero rather than one query per keyword
        # per crawled page — which would exhaust the 100/day free tier in one audit.
        nominated_keywords = _match_rank_target(page_url, rank_targets)
        rank_data = (
            rank_checker.check_rankings(
                page_url, nominated_keywords, config, max_keywords=len(nominated_keywords)
            )
            if enable_rank_check and nominated_keywords else []
        )
        # Competitor-gap fetches (via `crawler._fetch`) reuse the crawler's own
        # HTTP machinery, but that crawler instance still has its
        # `event_callback` wired up from `crawler.crawl()` above. Left as-is,
        # a 404/timeout/redirect on a *competitor's* URL would be broadcast to
        # the live activity feed as if it happened on the audited site. Null
        # the callback out for the duration of the suggestions call so only
        # audit-target crawl events ever reach the feed.
        # When rank_targets were supplied at all, suggestions are scoped to
        # nominated pages only — generating them for every other crawled page
        # would fire up to 3 synchronous Google Autocomplete requests each
        # (5s timeout apiece) from the no-rank-data fallback, and would offer
        # ungrounded suggestions on pages the user never asked about while the
        # one page they did nominate correctly shows none pre-credentials.
        # When rank_targets is None/empty, `enable_keyword_suggestions` keeps
        # its original site-wide behaviour: it is a documented standalone API
        # capability (docs/api.md) independent of rank tracking, and direct
        # API callers who never send rank_targets must not silently regress.
        suggestions_allowed = (
            not rank_targets or nominated_keywords is not None
        )
        saved_event_callback = crawler.event_callback
        crawler.event_callback = None
        try:
            suggestions = (
                keyword_suggestions.suggest_keywords(
                    keyword_data, rank_data, config,
                    fetch_page=crawler._fetch, page_url=page_url,
                    enable_competitor_gap=enable_competitor_gap,
                )
                if enable_keyword_suggestions and suggestions_allowed else []
            )
        finally:
            crawler.event_callback = saved_event_callback
        page_meta[page_url]["keyword_analysis"] = {
            "top_keywords": keyword_data,
            "rankings": rank_data,
            "suggested_keywords": suggestions,
        }
        page_data_for_dupes.append(analysis_result.dupe_row)



    site_wide = analysis.build_link_graph_stats(crawler)
    duplicates = analysis.find_duplicates(page_data_for_dupes)
    near_dupes, near_duplicate_mode = analysis.find_near_duplicates(
        page_data_for_dupes, signatures=signatures
    )
    redirects = analysis.redirect_report(crawler)
    broken_links = analysis.broken_link_report(crawler)

    recommendations = ai_suggestions.generate_recommendations(all_page_issues, site_wide)
    issue_freq = ai_suggestions.issue_frequency_summary(all_page_issues)

    exec_summary = report.build_executive_summary(
        crawler, all_page_issues, site_wide, duplicates, redirects, broken_links, recommendations
    )
    page_rows = report.build_page_level_report(crawler, all_page_issues, page_meta)

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

    result_data = {
        "executive_summary": exec_summary,
        "site_wide_analysis": site_wide,
        "duplicates": duplicates,
        "near_duplicate_content": near_dupes,
        "near_duplicate_mode": near_duplicate_mode,
        "redirects": redirects,
        "broken_links": broken_links,
        "recommendations": recommendations,
        "issue_frequency": issue_freq,
        "pages": page_rows,
        "rank_targets": [
            {"url": t.url, "keywords": list(t.keywords)} for t in (rank_targets or [])
        ],
        "architecture": {
            "nodes": arch_nodes,
            "links": arch_links,
        },
        "page_issues_detail": {u: v for u, v in all_page_issues.items()},
        "psi_metrics": psi_results,
        "robots_txt": crawler.robots_txt_content,
        "sitemaps_found": crawler.sitemaps_found,
        "sitemap_urls": list(crawler.sitemap_urls),
        "elapsed_seconds": round(time.monotonic() - started_at, 1),
        "note": "Audit executed directly via native Python engine.",
    }

    session_store.save_session({
        "id": f"sess_{int(time.time())}",
        "url": url,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "auditResult": result_data,
    })

    return result_data
