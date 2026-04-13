"""FastAPI application factory for the OmniLocation Web UI."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core.device_manager import DevicePool
from core.exceptions import OmniLocationError
from core.simulator import Simulator
from web.routers import devices as devices_router
from web.routers import gpx as gpx_router
from web.routers import simulation as simulation_router

logger = logging.getLogger(__name__)

# Ensure upload folder exists
os.makedirs(gpx_router.UPLOAD_FOLDER, exist_ok=True)

templates = Jinja2Templates(directory="web/templates")


# --- WebSocket Manager ---

class ConnectionManager:
    """Manages active WebSocket connections."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        stale: List[WebSocket] = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                stale.append(connection)
        for connection in stale:
            self.disconnect(connection)


manager = ConnectionManager()


async def broadcast_status_loop(simulator: Simulator):
    """Background task to broadcast simulation status via WebSocket."""
    logger.info("Starting WebSocket broadcast loop...")
    try:
        while True:
            if manager.active_connections:
                delay = 0.5 if simulator.active else 2.0
                await manager.broadcast(simulator.status)
            else:
                delay = 1.0
            await asyncio.sleep(delay)
    except asyncio.CancelledError:
        logger.info("WebSocket broadcast loop cancelled.")


# --- Lifespan ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manages the application lifecycle and shared resources."""
    device_pool = DevicePool()
    simulator = Simulator(device_pool)

    app.state.device_pool = device_pool
    app.state.simulator = simulator

    logger.info("Core components initialized.")

    broadcast_task = asyncio.create_task(broadcast_status_loop(simulator))

    yield

    logger.info("Shutting down core components...")
    broadcast_task.cancel()
    try:
        await broadcast_task
    except asyncio.CancelledError:
        pass

    await simulator.stop()


# --- Application Factory ---

def create_app() -> FastAPI:
    """Creates and configures the FastAPI application."""

    app = FastAPI(
        title="OmniLocation",
        description="Distributed Multi-Device Location Simulation System",
        version="2.1.0",
        lifespan=lifespan,
    )

    app.mount("/static", StaticFiles(directory="web/static"), name="static")

    # --- Exception Handlers ---

    @app.exception_handler(OmniLocationError)
    async def omnilocation_exception_handler(request: Request, exc: OmniLocationError):
        logger.warning("OmniLocation error: %s [%s]", exc.message, exc.code)
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception("Unexpected error: %s", str(exc))
        return JSONResponse(
            status_code=500,
            content={
                "error": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred. Please try again later.",
                "status": 500,
            },
        )

    # --- WebSocket ---

    @app.websocket("/ws/status")
    async def websocket_endpoint(websocket: WebSocket):
        await manager.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(websocket)
        except Exception:
            manager.disconnect(websocket)

    # --- HTML ---

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        tianditu_key = os.getenv("TIANDITU_KEY", "")
        return templates.TemplateResponse(
            request, "index.html", {"tianditu_key": tianditu_key}
        )

    # --- API Routers ---
    app.include_router(devices_router.router)
    app.include_router(gpx_router.router)
    app.include_router(simulation_router.router)

    return app
