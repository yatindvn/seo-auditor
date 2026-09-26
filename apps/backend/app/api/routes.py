import logging
import time
import asyncio
from typing import Any, Dict, List, Literal, Optional
from fastapi import APIRouter, HTTPException, Query, Path, BackgroundTasks
from app.schemas.schemas import AuditRequestParams
from app.services.audit_service import run_full_audit
import app.services.audit_service as audit_service
from app.models.session_model import session_store
from fastapi.responses import Response
from app.websocket.ws_manager import ws_manager
from app.utils.report import (
    export_csv, export_excel, export_html_report, export_json, export_pdf_summary,
)

router = APIRouter()
logger = logging.getLogger("seo_auditor")

# Audits live in their own SQLite file under config.SESSION_DIR, reached through
# session_store. There is no process-local session dict any more: it did not
# survive a restart, and at 5000 pages it held tens of megabytes per audit.



# Fields /api/audit/latest carries. Everything else -- the page rows, the
# per-page issue detail, the architecture graph -- is read from its own
# paginated endpoint. Sending all of it at once was tens of megabytes at 5000
# pages, more than the dashboard could store or parse.
SUMMARY_FIELDS = (
    "executive_summary", "site_wide_analysis", "recommendations",
    "issue_frequency", "duplicates", "redirects", "rank_targets",
    "near_duplicate_mode", "elapsed_seconds", "degraded", "partial",
    "robots_txt", "sitemaps_found", "psi_metrics", "note",
)


def _require_session(session_id: str):
    """The session's database, or a 404.

    Replaces a lookup in a process-local dict, which meant a restart lost every
    session the dashboard still had a link to.
    """
    db = session_store.get(session_id)
    if db is None:
        raise HTTPException(status_code=404, detail="No audit session found")
    return db


def _require_result(session_id: str) -> Dict[str, Any]:
    """The finished audit for a session.

    A database with no summary row is a crawl still running: the dashboard polls
    from the moment it starts, and 404 is what it already expects meanwhile.
    """
    summary = _require_session(session_id).get_summary()
    if not summary or not summary.get("auditResult"):
        raise HTTPException(status_code=404, detail="No audit session found")
    return summary["auditResult"]


def _page(items: List[Any], total: int, offset: int, limit: int) -> Dict[str, Any]:
    return {"items": items, "total": total, "offset": offset, "limit": limit}


def log_crawl_failure(session_id: str, exc: Exception) -> None:
    """Log a crawl failure with its traceback instead of writing to a plain file."""
    logger.error("Crawl failed for session %s: %s", session_id, exc, exc_info=exc)

@router.post("/audit")
async def execute_audit(params: AuditRequestParams, background_tasks: BackgroundTasks):
    url = params.url.strip()
    session_id = f"sess_{int(time.time() * 1000)}"

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    start_time = time.time()

    def event_callback(event_type: str, payload: dict):
        if event_type == "page_crawled":
            asyncio.run_coroutine_threadsafe(ws_manager.emit_page_crawled(payload, session_id), loop)
        elif event_type in ("link_progress", "redirect", "broken_link", "timeout"):
            msg = f"Found {event_type}"
            if event_type == "redirect": msg = f"Redirected {payload['url']} -> {payload['to']}"
            elif event_type == "broken_link": msg = f"Broken Link {payload['url']} (Status {payload['status']})"
            elif event_type == "timeout": msg = f"Timeout accessing {payload['url']}"
            elif event_type == "link_progress":
                msg = (f"{payload['internal_total']:,} internal links found "
                       f"({payload['external_total']:,} external)")
            
            payload_data = {
                "id": f"act_{int(time.time()*1000)}_{event_type}",
                "type": event_type,
                "message": msg,
                "timestamp": int(time.time() * 1000),
                "session_id": session_id,
            }
            asyncio.run_coroutine_threadsafe(ws_manager.broadcast("activity:new", payload_data), loop)

    def background_task():
        try:
            asyncio.run_coroutine_threadsafe(ws_manager.broadcast("crawl:start", {"url": url, "session_id": session_id}), loop)
            
            data = run_full_audit(
                url=url,
                session_id=session_id,
                max_pages=params.max_pages or 8,
                max_depth=params.max_depth or 1,
                ignore_robots=params.ignore_robots or False,
                enable_keyword_analysis=params.enable_keyword_analysis if params.enable_keyword_analysis is not None else True,
                enable_keyword_suggestions=params.enable_keyword_suggestions or False,
                enable_rank_check=params.enable_rank_check or False,
                enable_competitor_gap=params.enable_competitor_gap or False,
                target_keywords=params.target_keywords,
                rank_targets=params.rank_targets,
                event_callback=event_callback,
                progress_callback=lambda count, total, current_url: asyncio.run_coroutine_threadsafe(
                    ws_manager.broadcast("crawl:progress", {
                        "session_id": session_id,
                        "stage": "Crawling Pages...",
                        "progress": int((count / total) * 100),
                        "pages_crawled": count,
                        "current_url": current_url,
                        "queue_remaining": total - count,
                        "speed_pages_per_sec": round(count / max(1, time.time() - start_time), 1),
                        "elapsed_seconds": int(time.time() - start_time),
                        "eta_seconds": int((total - count) / max(0.1, count / max(1, time.time() - start_time))),
                    }), loop
                )
            )
            # The audit persisted itself as it crawled; nothing to stash here.
            asyncio.run_coroutine_threadsafe(ws_manager.broadcast("crawl:complete", {"status": "success", "session_id": session_id}), loop)
        except Exception as exc:
            log_crawl_failure(session_id, exc)
            asyncio.run_coroutine_threadsafe(ws_manager.broadcast("crawl:error", {"error": str(exc), "session_id": session_id}), loop)

    background_tasks.add_task(background_task)
    return {"status": "started", "session_id": session_id}


@router.get("/audit/latest")
def get_latest_audit(session_id: str = Query(...)):
    """The audit summary. Page rows, issue detail and the graph have their own
    endpoints -- this response is what the dashboard needs to paint first."""
    result = _require_result(session_id)
    db = _require_session(session_id)
    _, page_count = db.get_pages(limit=1)

    summary = {field: result.get(field) for field in SUMMARY_FIELDS if field in result}
    summary["page_count"] = page_count
    return summary


@router.post("/audit/pause")
def pause_audit(session_id: str = Query(...)):
    crawler = audit_service.get_crawler(session_id)
    if crawler:
        crawler.is_paused = True
        return {"status": "paused"}
    return {"status": "not_running"}


@router.post("/audit/resume")
def resume_audit(session_id: str = Query(...)):
    crawler = audit_service.get_crawler(session_id)
    if crawler:
        crawler.is_paused = False
        return {"status": "resumed"}
    return {"status": "not_running"}


@router.post("/audit/stop")
def stop_audit(session_id: str = Query(...)):
    crawler = audit_service.get_crawler(session_id)
    if crawler:
        crawler.is_stopped = True
        return {"status": "stopped"}
    return {"status": "not_running"}

@router.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "seo-auditor-native-python-backend",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# Typed as a Literal so an unknown column is a 422 at the edge rather than a
# ValueError from the database layer. Both guards stay: the database is also
# called from the CLI.
SortablePageColumn = Literal[
    "url", "depth", "status", "word_count", "response_time_ms",
    "internal_links_count", "external_links_count", "issue_count",
]


@router.get("/pages")
def get_pages(
    session_id: str = Query(...),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    sort: SortablePageColumn = Query("depth"),
    order: Literal["asc", "desc"] = Query("asc"),
    filter: Optional[str] = Query(None, max_length=200),
    status: Optional[int] = Query(None),
    has_issues: Optional[bool] = Query(None),
):
    db = _require_session(session_id)
    items, total = db.get_pages(
        offset=offset, limit=limit, sort=sort, order=order,
        filter_text=filter, status=status, has_issues=has_issues,
    )
    return _page(items, total, offset, limit)


@router.get("/issues")
def get_issues(
    session_id: str = Query(...),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    severity: Optional[Literal["critical", "warning", "info"]] = Query(None),
    code: Optional[str] = Query(None, max_length=100),
):
    """Per-page issues. Site-wide recommendations stay on /api/audit/latest --
    there are tens of those, not tens of thousands."""
    db = _require_session(session_id)
    items, total = db.get_issues(offset=offset, limit=limit, severity=severity, code=code)
    return _page(items, total, offset, limit)


@router.get("/duplicates")
def get_duplicates(
    session_id: str = Query(...),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
):
    """Near-duplicate pairs, with the mode that produced their similarities.

    `mode` travels with the numbers because it changes what they mean: above
    500 pages a similarity is a MinHash estimate, not an exact Jaccard.
    """
    result = _require_result(session_id)
    pairs = result.get("near_duplicate_content", [])
    window = pairs[offset:offset + limit]
    body = _page(window, len(pairs), offset, limit)
    body["mode"] = result.get("near_duplicate_mode", "exact")
    return body


@router.get("/architecture")
def get_architecture(
    session_id: str = Query(...),
    expand: Optional[str] = Query(None, max_length=200),
):
    """Path-clustered by default; one cluster's pages when expanded.

    A node per page is ~5000 nodes and a few hundred thousand edges at the Full
    Site Crawl preset, which no browser draws interactively.
    """
    db = _require_session(session_id)
    summary = db.get_summary() or {}
    start_url = summary.get("url") or ""

    if expand:
        nodes, links = db.get_cluster_pages(start_url, expand)
        return {"clustered": False, "expanded": expand, "nodes": nodes, "links": links}

    return {
        "clustered": True,
        "nodes": db.get_clusters(start_url),
        "links": db.get_cluster_edges(start_url),
    }


@router.get("/history")
def get_history(session_id: str = Query(None)):
    sessions = session_store.get_all_sessions()
    latest = None
    if session_id:
        db = session_store.get(session_id)
        summary = db.get_summary() if db else None
        latest = (summary or {}).get("auditResult")
    comparison = session_store.get_history_comparison(latest) if latest else None
    return {"sessions": sessions, "comparison": comparison}



@router.delete("/history/{session_id}")
def delete_history_session(session_id: str):
    success = session_store.delete_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "deleted"}


@router.get("/page/{page_id:path}")
def get_page_by_id(page_id: str, session_id: str = Query(...)):
    """One page by URL: a primary-key read rather than a scan of every row."""
    db = _require_session(session_id)
    page = db.get_page(page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")
    return page


@router.get("/internal-links")
def get_internal_links(
    session_id: str = Query(...),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
):
    result = _require_result(session_id)
    broken = result.get("broken_links", [])
    return {
        "site_wide_analysis": result.get("site_wide_analysis"),
        "broken_links": _page(broken[offset:offset + limit], len(broken), offset, limit),
    }


@router.get("/export/{fmt}")
def export_report(fmt: str, session_id: str = Query(...)):
    result = _require_result(session_id)
        
    if fmt == "json":
        data = export_json(None, result)
        return Response(content=data, media_type="application/json", headers={"Content-Disposition": 'attachment; filename="audit_report.json"'})
    elif fmt == "csv":
        data = export_csv(None, result.get("pages", []))
        return Response(content=data, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="pages.csv"'})
    elif fmt == "xlsx":
        sheets = {
            "Executive Summary": [result.get("executive_summary", {}).get("health_score", {})],
            "Pages": result.get("pages", []),
            "Recommendations": result.get("recommendations", []),
            "Broken Links": result.get("broken_links", []),
        }
        data = export_excel(None, sheets)
        return Response(content=data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="audit_report.xlsx"'})
    elif fmt == "pdf":
        data = export_pdf_summary(None, result.get("executive_summary", {}))
        return Response(content=data, media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="audit_summary.pdf"'})
    elif fmt == "html":
        data = export_html_report(None, result.get("executive_summary", {}), result.get("pages", []))
        return Response(content=data, media_type="text/html", headers={"Content-Disposition": 'attachment; filename="audit_report.html"'})
    else:
        raise HTTPException(status_code=400, detail="Invalid format requested")
