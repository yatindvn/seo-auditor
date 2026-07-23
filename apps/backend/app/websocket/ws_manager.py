import json
import asyncio
from typing import List, Dict, Any
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        await self.send_personal_message(
            {"event": "connect", "message": "Connected to Native Python SEO Auditor WebSocket Server"},
            websocket,
        )

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def send_personal_message(self, message: Dict[str, Any], websocket: WebSocket):
        try:
            await websocket.send_text(json.dumps(message))
        except Exception:
            self.disconnect(websocket)

    async def broadcast(self, event: str, payload: Any):
        message = json.dumps({"event": event, "payload": payload})
        for connection in list(self.active_connections):
            try:
                await connection.send_text(message)
            except Exception:
                self.disconnect(connection)

    async def emit_page_crawled(self, page_data: Dict[str, Any], session_id: str):
        page_payload = page_data.copy()
        page_payload["session_id"] = session_id
        await self.broadcast("page:crawled", page_payload)
        await self.broadcast("activity:new", {
            "id": f"act_{int(asyncio.get_event_loop().time())}",
            "type": "page_crawled",
            "message": f"Crawled {page_data.get('url')} (Status: {page_data.get('status', 200)}, Depth: {page_data.get('depth', 1)})",
            "timestamp": page_data.get("timestamp"),
            "url": page_data.get("url"),
            "session_id": session_id,
        })


ws_manager = ConnectionManager()
