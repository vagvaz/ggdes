"""Shared utilities for web routes."""

from typing import Any

from fastapi import WebSocket

from ggdes.config import GGDesConfig, load_config
from ggdes.kb import KnowledgeBaseManager


class ConnectionManager:
    """Manage WebSocket connections for real-time updates."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast message to all connected clients."""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)

        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)


manager = ConnectionManager()


def get_kb() -> KnowledgeBaseManager:
    """Get knowledge base manager."""
    config, _ = load_config()
    return KnowledgeBaseManager(config)


def get_config() -> GGDesConfig:
    """Get configuration."""
    config, _ = load_config()
    return config
