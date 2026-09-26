import logging
import time
import asyncio
from typing import Dict, Any, List
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

active_sessions: Dict[str, Any] = {}


def log_crawl_failure(session_id: str, exc: Exception) -> None:
    """Log a crawl failure with its traceback instead of writing to a plain file."""
    logger.error("Crawl failed for session %s: %s", session_id, exc, exc_info=exc)

@router.post("/audit")
async def execute_audit(params: AuditRequestParams, background_tasks: BackgroundTasks):
    url = params.url.strip()
    session_id = f"sess_{int(time.time() * 1000)}"
    active_sessions[session_id] = {}

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
        elif event_type in ("internal_link", "external_link", "redirect", "broken_link", "timeout"):
            msg = f"Found {event_type}"
            if event_type == "redirect": msg = f"Redirected {payload['url']} -> {payload['to']}"
            elif event_type == "broken_link": msg = f"Broken Link {payload['url']} (Status {payload['status']})"
            elif event_type == "timeout": msg = f"Timeout accessing {payload['url']}"
            elif event_type == "internal_link": msg = f"Internal Link found: {payload.get('to')}"
            elif event_type == "external_link": msg = f"External Link found: {payload.get('to')}"
            
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
            active_sessions[session_id] = data
            asyncio.run_coroutine_threadsafe(ws_manager.broadcast("crawl:complete", {"status": "success", "session_id": session_id}), loop)
        except Exception as exc:
            log_crawl_failure(session_id, exc)
            asyncio.run_coroutine_threadsafe(ws_manager.broadcast("crawl:error", {"error": str(exc), "session_id": session_id}), loop)

    background_tasks.add_task(background_task)
    return {"status": "started", "session_id": session_id}


@router.get("/audit/latest")
def get_latest_audit(session_id: str = Query(...)):
    if session_id not in active_sessions or not active_sessions[session_id]:
        raise HTTPException(status_code=404, detail="No audit session found")
    return active_sessions[session_id]


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


@router.get("/pages")
def get_pages(session_id: str = Query(...)):
    if session_id not in active_sessions or not active_sessions[session_id]:
        raise HTTPException(status_code=404, detail="No audit session found")
    return active_sessions[session_id].get("pages", [])


@router.get("/issues")
def get_issues(session_id: str = Query(...)):
    if session_id not in active_sessions or not active_sessions[session_id]:
        raise HTTPException(status_code=404, detail="No audit session found")
    return active_sessions[session_id].get("recommendations", [])


@router.get("/architecture")
def get_architecture(session_id: str = Query(...)):
    if session_id not in active_sessions or not active_sessions[session_id]:
        raise HTTPException(status_code=404, detail="No audit session found")
    return active_sessions[session_id].get("architecture", {"nodes": [], "links": []})


@router.get("/history")
def get_history(session_id: str = Query(None)):
    sessions = session_store.get_all_sessions()
    latest = active_sessions.get(session_id) if session_id else None
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
    if session_id not in active_sessions or not active_sessions[session_id]:
        raise HTTPException(status_code=404, detail="No audit session found")
    for page in active_sessions[session_id].get("pages", []):
        if page.get("url") == page_id or page_id in page.get("url", ""):
            return page
    raise HTTPException(status_code=404, detail="Page not found")


@router.get("/internal-links")
def get_internal_links(session_id: str = Query(...)):
    if session_id not in active_sessions or not active_sessions[session_id]:
        raise HTTPException(status_code=404, detail="No audit session found")
    return {
        "site_wide_analysis": active_sessions[session_id].get("site_wide_analysis"),
        "broken_links": active_sessions[session_id].get("broken_links", []),
    }


@router.get("/export/{fmt}")
def export_report(fmt: str, session_id: str = Query(...)):
    if session_id not in active_sessions or not active_sessions[session_id]:
        raise HTTPException(status_code=404, detail="No audit session found")
        
    result = active_sessions[session_id]
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
