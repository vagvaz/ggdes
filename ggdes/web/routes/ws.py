"""WebSocket endpoint for real-time updates."""

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ggdes.web.manager import manager

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time updates."""
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive and handle client messages
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                # Handle subscription requests, etc.
                if message.get("action") == "subscribe":
                    await websocket.send_json(
                        {
                            "type": "subscribed",
                            "analysis_id": message.get("analysis_id"),
                        }
                    )
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)
