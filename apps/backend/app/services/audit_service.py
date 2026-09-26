import concurrent.futures
import logging
import os
import time
import asyncio
from concurrent.futures.process import BrokenProcessPool
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


# Below this page cap the checks run in-process. Spawning worker processes for
# an eight-page audit costs more than it saves -- process startup, plus pickling
# every page across the boundary -- and most audits are small.
POOL_MIN_PAGES = 50

# How many analyses may be outstanding before the crawl waits for some to land.
# This is what bounds the HTML held in memory: each pending analysis holds one
# page's markup until a worker takes it.
MAX_PENDING_ANALYSES = 64

# Rows per database write. Batched because the crawl produces rows
# continuously and a transaction per page would fsync thousands of times.
WRITE_BATCH_SIZE = 50


def _submit_analysis(pool, payload):
    """Start one page's analysis, in a worker when there is a pool.

    A seam, deliberately: the single point where a pool failure can be
    simulated, and where "pool" and "no pool" differ.
    """
    if pool is None:
        return page_pipeline.analyze_page(payload)
    return pool.submit(page_pipeline.analyze_page, payload)


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
            session_id=session_id,
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
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    # Monotonic, not time.time(): this is a duration, and monotonic cannot be
    # skewed by an NTP correction or a manual clock change mid-audit.
    started_at = time.monotonic()

    all_page_issues = {}
    page_meta = {}
    page_data_for_dupes = []
    psi_results: Dict[str, Any] = {}
    signatures: Dict[str, bytes] = {}
    # Decided from the page cap, not the realised count: each page is signed (or
    # not) as it is analysed, long before the crawl's final size is known.
    # getattr because the cap is a Crawler attribute and callers may pass any
    # object exposing crawler.results.
    page_cap = getattr(crawler, "max_pages", 0)
    compute_signature = page_cap > analysis.EXACT_PATH_MAX_PAGES

    analyses: Dict[str, Any] = {}
    pending: Dict[str, Any] = {}
    degraded = False

    # Rows go to disk as they are produced rather than being assembled in one
    # structure at the end. The id is generated here when a caller (the CLI,
    # a test) does not supply one, so every audit is persisted the same way.
    session_id = session_id or f"sess_{int(time.time())}"
    db = session_store.open_session(session_id)
    row_buffer: List[Dict[str, Any]] = []

    def _flush_rows(force: bool = False) -> None:
        if not row_buffer or (not force and len(row_buffer) < WRITE_BATCH_SIZE):
            return
        db.add_pages(row_buffer)
        row_buffer.clear()

    def _record(url: str, result, page_analysis) -> None:
        """Queue one page's row, and write its links and signature."""
        meta = dict(page_analysis.meta)
        row_buffer.append({
            "url": url,
            "final_url": result.final_url,
            "depth": result.depth,
            "status": result.status_code,
            "response_time_ms": result.response_time_ms,
            "content_type": result.content_type,
            "title": meta.get("title"),
            "meta_description": meta.get("meta_description"),
            "h1": meta.get("h1"),
            "canonical": meta.get("canonical"),
            "word_count": meta.get("word_count", 0),
            "char_count": meta.get("char_count", 0),
            "internal_links_count": meta.get("internal_links_count", 0),
            "external_links_count": meta.get("external_links_count", 0),
            "images_count": meta.get("images_count", 0),
            "missing_alt_count": meta.get("missing_alt_count", 0),
            "meta_robots": meta.get("meta_robots"),
            "lang": meta.get("lang"),
            "error": result.error or ("audit failed" if page_analysis.failed else None),
            "meta": meta,
            "issues": page_analysis.issues,
        })
        edges = [(url, target, True) for target in page_analysis.internal_links]
        edges += [(url, target, False) for target in page_analysis.external_links]
        if edges:
            db.add_links(edges)
        if page_analysis.signature:
            db.add_signature(url, page_analysis.signature)
        _flush_rows()

    def _resolve(url, outcome):
        """Store a completed analysis, or the record of one that raised."""
        try:
            resolved = outcome.result() if hasattr(outcome, "result") else outcome
        except Exception as exc:
            logger.error("Audit checks failed for %s: %s", url, exc, exc_info=exc)
            resolved = page_pipeline.failed_analysis(url, exc)
        analyses[url] = resolved
        # A page that could not be audited is still written, saying so. Missing
        # from the table would read as never crawled.
        _record(url, crawler.results[url], resolved)

    def on_page(result):
        """Hand one fetched page to stage 2 and let the crawl carry on.

        Returns None so the crawler finds its own links: blocking here for a
        worker would leave every other worker idle. Measured, the duplicate
        parse is 11% of a page's analysis and the parallelism it would forfeit
        is worth about 50%.
        """
        nonlocal degraded
        payload = page_pipeline.PagePayload(
            url=result.url,
            final_url=result.final_url,
            status_code=result.status_code,
            headers=result.headers,
            html=result.html,
            depth=result.depth,
            redirect_chain=result.redirect_chain,
            response_time_ms=result.response_time_ms,
            content_type=result.content_type,
            error=result.error,
            enable_keyword_analysis=enable_keyword_analysis,
            target_keywords=target_keywords,
            compute_signature=compute_signature,
        )
        try:
            outcome = _submit_analysis(pool, payload)
        except (BrokenProcessPool, OSError) as exc:
            # Slow beats failed: a pool that cannot run must not cost the crawl.
            if not degraded:
                logger.error(
                    "Process pool unusable, analysing in-process: %s", exc, exc_info=exc
                )
            degraded = True
            outcome = page_pipeline.analyze_page(payload)
        except Exception as exc:
            # Logged here as well as in _resolve: catching without logging would
            # turn a loud bug into an invisible one, and this is the in-process
            # path, which _resolve never sees.
            logger.error("Audit checks failed for %s: %s", result.url, exc, exc_info=exc)
            outcome = page_pipeline.failed_analysis(result.url, exc)

        if hasattr(outcome, "result"):
            pending[result.url] = outcome
            # Bounded, because each pending analysis holds one page's markup.
            while len(pending) >= MAX_PENDING_ANALYSES:
                oldest = next(iter(pending))
                _resolve(oldest, pending.pop(oldest))
        else:
            _resolve(result.url, outcome)

        # The crawler keeps a PageResult per page for the whole audit. Once the
        # markup is on its way to a worker, a second copy here is what turns a
        # 5000-page crawl into hundreds of megabytes.
        result.html = ""
        return None

    pool = None
    try:
        if page_cap > POOL_MIN_PAGES:
            pool = concurrent.futures.ProcessPoolExecutor(max_workers=os.cpu_count() or 2)
        crawler.crawl(
            progress_callback=progress_callback,
            event_callback=event_callback,
            on_page=on_page,
        )
        for url, outcome in list(pending.items()):
            _resolve(url, outcome)
        pending.clear()
        _flush_rows(force=True)
    finally:
        if pool is not None:
            pool.shutdown(wait=True)

    # 0 means skip the requests entirely (the CLI's --skip-external-links), not
    # issue zero-length ones. 25 is the API's long-standing default.
    if external_link_check_limit:
        crawler.check_external_links(max_check=external_link_check_limit)

    partial = bool(getattr(crawler, "is_stopped", False))

    for page_url, page in crawler.results.items():
        # Stage 2 already ran, during the crawl. What is left here is what must
        # not be multiplied across worker processes: the quota'd Google APIs and
        # PageSpeed Insights.
        analysis_result = analyses.get(page_url)
        if analysis_result is None:
            # A page the crawl recorded but never handed over -- a stop landing
            # between the two. Reported, rather than dropped silently.
            analysis_result = page_pipeline.failed_analysis(
                page_url, RuntimeError("page was not analysed")
            )

        if analysis_result.failed:
            all_page_issues[page_url] = analysis_result.issues
            page_meta[page_url] = analysis_result.meta
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

    # node_url, not url: this loop used to rebind the function's `url`
    # parameter, so everything after it saw the last crawled page instead of
    # the audited site -- which is what the saved session recorded as the URL
    # it had audited.
    for node_url, res in crawler.results.items():
        arch_nodes.append({
            "id": node_url,
            "url": node_url,
            "label": node_url.replace("https://", "").replace("http://", "").split("?")[0],
            "depth": res.depth,
            "isBroken": node_url in broken_set or (res.status_code is not None and res.status_code >= 400),
            "isOrphan": node_url in orphan_set,
            "isDeadEnd": node_url in dead_end_set,
            "isDeep": res.depth >= 3,
            "isHub": node_url in hub_set,
            "inboundCount": len(crawler.inbound_links.get(node_url, set())),
            "outboundCount": len(crawler.link_graph.get(node_url, set())),
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
        "degraded": degraded,
        "partial": partial,
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

    # Written through the session's own database rather than save_session,
    # which would open a second one and discard the rows just persisted.
    # auditResult is still carried whole because the history panel restores a
    # past audit from it; it stops being stored here once the endpoints read
    # rows instead.
    db.set_summary({
        "url": url,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "saved_at": time.time_ns(),
        "auditResult": result_data,
    })

    return result_data
