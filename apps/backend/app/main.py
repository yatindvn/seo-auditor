import sys
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router as api_router
from app.config import config
from app.websocket.ws_manager import ws_manager

@asynccontextmanager
async def _lifespan(app):
    """Starts the in-process scheduler when SCHEDULER_ENABLED, and stops it on
    shutdown so a redeploy never leaves a half-started audit job behind."""
    scheduler = None
    if config.SCHEDULER_ENABLED:
        from app.scheduler.jobs import start_scheduler
        scheduler = start_scheduler()
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)


app = FastAPI(
    lifespan=_lifespan,
    title="SEO Auditor Native Python Backend",
    description="Pure Python Crawling, Audit, REST API & WebSocket Platform",
    version="1.0.0",
)

def _cors_options():
    """Pick a CORS policy that is actually valid.

    The CORS spec forbids `Access-Control-Allow-Origin: *` on a credentialed
    request, so wildcard-plus-credentials is not a stricter wildcard -- it is a
    contradiction, and Starlette silently resolves it by dropping the credentials
    header. Choose deliberately instead:

      - ALLOWED_ORIGINS set   -> echo those origins, credentials permitted.
      - ALLOWED_ORIGINS unset -> wildcard, credentials off. Keeps local
        development (and any same-origin deployment) working without pretending
        to support credentialed cross-origin calls.
    """
    if config.ALLOWED_ORIGINS:
        return {
            "allow_origins": config.ALLOWED_ORIGINS,
            "allow_credentials": True,
            "allow_methods": ["*"],
            "allow_headers": ["*"],
        }
    return {
        "allow_origins": ["*"],
        "allow_credentials": False,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }


app.add_middleware(CORSMiddleware, **_cors_options())

app.include_router(api_router, prefix="/api")
from app.api.projects import router as projects_router  # noqa: E402
app.include_router(projects_router, prefix="/api")
from app.api.rank import router as rank_router  # noqa: E402
app.include_router(rank_router, prefix="/api")
from app.api.keywords import router as keywords_router  # noqa: E402
app.include_router(keywords_router, prefix="/api")
from app.api.vitals import router as vitals_router  # noqa: E402
app.include_router(vitals_router, prefix="/api")
from app.api.rendering import router as rendering_router  # noqa: E402
app.include_router(rendering_router, prefix="/api")

from app.api.cron import router as cron_router  # noqa: E402
app.include_router(cron_router, prefix="/api")



@app.websocket("/ws")
@app.websocket("/")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text('{"event":"pong"}')
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=5000, reload=True)
