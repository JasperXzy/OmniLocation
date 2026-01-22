"""FastAPI application factory for the OmniLocation Web UI."""

import logging
import os
import shutil
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from core.device_manager import DevicePool
from core.exceptions import (
    OmniLocationError,
    ValidationError,
    ResourceNotFoundError,
    InvalidFileError,
    GPXParseError,
)
from core.gpx_handler import GPXHandler
from core.simulator import Simulator

# Configuration
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'gpx'}

logger = logging.getLogger(__name__)

# Ensure upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Templates
templates = Jinja2Templates(directory="web/templates")


# --- Pydantic Models ---

class RenameDeviceRequest(BaseModel):
    udid: str
    name: str

class StartSimulationRequest(BaseModel):
    filename: str
    udids: List[str]
    loop: bool = False
    speed: float = 1.0
    target_duration: Optional[float] = None


# --- Helper Functions ---

def allowed_file(filename: str) -> bool:
    """Checks if the file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# --- Lifespan Manager (Startup/Shutdown) ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manages the application lifecycle and shared resources."""
    # 1. Initialize Core Components
    device_pool = DevicePool()
    simulator = Simulator(device_pool)
    
    # Store in app.state for access in route handlers
    app.state.device_pool = device_pool
    app.state.simulator = simulator
    
    logger.info("Core components initialized.")
    
    yield  # Application runs here
    
    # 2. Cleanup
    logger.info("Shutting down core components...")
    # Add any cleanup logic here (e.g., stopping simulator if running)
    await simulator.stop()


# --- Application Factory ---

def create_app() -> FastAPI:
    """Creates and configures the FastAPI application."""
    
    app = FastAPI(
        title="OmniLocation",
        description="Distributed Multi-Device Location Simulation System",
        version="2.0.0",
        lifespan=lifespan
    )

    # Mount static files
    app.mount("/static", StaticFiles(directory="web/static"), name="static")

    # --- Exception Handlers ---

    @app.exception_handler(OmniLocationError)
    async def omnilocation_exception_handler(request: Request, exc: OmniLocationError):
        logger.warning("OmniLocation error: %s [%s]", exc.message, exc.code)
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_dict(),
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception("Unexpected error: %s", str(exc))
        return JSONResponse(
            status_code=500,
            content={
                "error": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred. Please try again later.",
                "status": 500
            },
        )

    # --- Routes ---

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        """Renders the main dashboard page."""
        tianditu_key = os.getenv("TIANDITU_KEY", "")
        return templates.TemplateResponse(
            "index.html", 
            {"request": request, "tianditu_key": tianditu_key}
        )

    @app.get("/api/devices")
    async def list_devices():
        """Lists connected devices after triggering a scan."""
        device_pool: DevicePool = app.state.device_pool
        devices = device_pool.scan_usb_devices()
        
        dev_list = []
        for d in devices:
            device_type = 'iOS' if d.__class__.__name__ == 'IOSDevice' else 'Android'
            dev_list.append({
                'udid': d.udid,
                'name': d.name,
                'real_name': d.real_name,
                'device_type': device_type,
                'connection_type': d.connection_type,
                'connected': d.connected
            })
        return dev_list

    @app.post("/api/devices/rename")
    async def rename_device(req: RenameDeviceRequest):
        """Renames a device."""
        device_pool: DevicePool = app.state.device_pool
        success = device_pool.rename_device(req.udid, req.name)
        if success:
            return {"message": "Device renamed successfully"}
        else:
            raise ResourceNotFoundError('Device', req.udid)

    @app.post("/api/upload")
    async def upload_file(file: UploadFile = File(...)):
        """Handles GPX file uploads."""
        if not file.filename:
            raise ValidationError('No file selected', field='file')
        
        if not allowed_file(file.filename):
            raise InvalidFileError('Only .gpx files are allowed', filename=file.filename)
        
        # Simple security check (FastAPI UploadFile.filename is user-provided)
        filename = os.path.basename(file.filename) 
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        
        try:
            with open(filepath, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
        except Exception as e:
            logger.error("Failed to save file %s: %s", filename, e)
            raise InvalidFileError(f'Failed to save file: {str(e)}', filename=filename)
            
        return {
            'message': 'File uploaded successfully',
            'filename': filename
        }

    @app.get("/api/gpx_files")
    async def list_gpx_files():
        """Lists available GPX files."""
        files = []
        if os.path.exists(UPLOAD_FOLDER):
            files = [
                f for f in os.listdir(UPLOAD_FOLDER)
                if f.endswith('.gpx')
            ]
        return files

    @app.delete("/api/gpx_files/{filename}")
    async def delete_gpx_file(filename: str):
        """Deletes a GPX file."""
        # Prevent directory traversal
        filename = os.path.basename(filename)
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        
        if not os.path.exists(filepath):
            raise ResourceNotFoundError('GPX file', filename)
        
        try:
            os.remove(filepath)
            return {'success': True, 'message': f'Deleted {filename}'}
        except Exception as e:
            logger.error("Failed to delete file %s: %s", filename, e)
            raise InvalidFileError(f'Failed to delete file: {str(e)}', filename=filename)

    @app.get("/api/gpx_files/{filename}/details")
    async def get_gpx_details(filename: str):
        """Gets metadata for a specific GPX file."""
        filename = os.path.basename(filename)
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        
        if not os.path.exists(filepath):
            raise ResourceNotFoundError('GPX file', filename)

        try:
            handler = GPXHandler(filepath)
            data = handler.parse()
            
            # Serialize points
            serialized_points = []
            for p in data['points']:
                point_dict = p.copy()
                if point_dict.get('time'):
                    point_dict['time'] = point_dict['time'].isoformat()
                serialized_points.append(point_dict)

            return {
                'filename': filename,
                'total_distance': data['total_distance'],
                'total_duration': data['total_duration'],
                'point_count': len(data['points']),
                'points': serialized_points
            }
        except Exception as e:
            logger.error("Failed to parse GPX file %s: %s", filename, e)
            raise GPXParseError(filename, str(e))

    @app.post("/api/start")
    async def start_simulation(req: StartSimulationRequest):
        """Starts the simulation."""
        simulator: Simulator = app.state.simulator
        
        filepath = os.path.join(UPLOAD_FOLDER, req.filename)
        if not os.path.exists(filepath):
            raise ResourceNotFoundError('GPX file', req.filename)

        if not req.udids:
            raise ValidationError('No devices selected for simulation', field='udids')

        # Parse GPX
        try:
            handler = GPXHandler(filepath)
            gpx_data = handler.parse()
            points = gpx_data['points']
            original_duration = gpx_data['total_duration']
            
            speed_multiplier = req.speed
            
            # Recalculate speed if target_duration is provided
            if req.target_duration is not None:
                if req.target_duration > 0 and original_duration > 0:
                    speed_multiplier = original_duration / req.target_duration
                    logger.info("Calculated speed %.2f based on target duration %.2fs", 
                                speed_multiplier, req.target_duration)

        except Exception as e:
            logger.error("Failed to parse GPX: %s", e)
            raise GPXParseError(req.filename, str(e))

        # Start simulation (Native Async Await!)
        await simulator.start(
            points, req.udids, loop_track=req.loop, speed_multiplier=speed_multiplier
        )

        return {
            'message': 'Simulation started',
            'device_count': len(req.udids),
            'speed_multiplier': speed_multiplier
        }

    @app.post("/api/stop")
    async def stop_simulation():
        """Stops the simulation."""
        simulator: Simulator = app.state.simulator
        await simulator.stop()
        return {'message': 'Simulation paused'}

    @app.post("/api/reset")
    async def reset_simulation():
        """Resets the simulation."""
        simulator: Simulator = app.state.simulator
        await simulator.reset()
        return {'message': 'Simulation reset and location cleared'}

    @app.get("/api/status")
    async def get_status():
        """Gets real-time simulation status."""
        simulator: Simulator = app.state.simulator
        return simulator.status

    return app
