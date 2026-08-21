import sys
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router as api_router
from app.config import config
from app.websocket.ws_manager import ws_manager

app = FastAPI(
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
