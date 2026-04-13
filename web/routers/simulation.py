"""Simulation control endpoints."""

import logging
import os
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.exceptions import GPXParseError, ResourceNotFoundError, ValidationError
from core.gpx_handler import GPXHandler
from core.simulator import Simulator
from web.dependencies import get_simulator
from web.routers.gpx import UPLOAD_FOLDER

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["simulation"])


class StartSimulationRequest(BaseModel):
    filename: str
    udids: List[str]
    loop: bool = False
    speed: float = 1.0
    target_duration: Optional[float] = None


@router.post("/start")
async def start_simulation(
    req: StartSimulationRequest,
    simulator: Simulator = Depends(get_simulator),
):
    """Starts the simulation."""
    filepath = os.path.join(UPLOAD_FOLDER, os.path.basename(req.filename))
    if not os.path.exists(filepath):
        raise ResourceNotFoundError('GPX file', req.filename)

    if not req.udids:
        raise ValidationError('No devices selected for simulation', field='udids')

    try:
        handler = GPXHandler(filepath)
        gpx_data = handler.parse()
        points = gpx_data['points']
        original_duration = gpx_data['total_duration']
        speed_multiplier = req.speed

        if req.target_duration is not None:
            if req.target_duration > 0 and original_duration > 0:
                speed_multiplier = original_duration / req.target_duration
                logger.info(
                    "Calculated speed %.2f based on target duration %.2fs",
                    speed_multiplier, req.target_duration,
                )
    except Exception as e:
        logger.error("Failed to parse GPX: %s", e)
        raise GPXParseError(req.filename, str(e))

    await simulator.start(
        points,
        req.udids,
        loop_track=req.loop,
        speed_multiplier=speed_multiplier,
        target_duration=req.target_duration,
    )

    return {
        'message': 'Simulation started',
        'device_count': len(req.udids),
        'speed_multiplier': speed_multiplier,
    }


@router.post("/stop")
async def stop_simulation(simulator: Simulator = Depends(get_simulator)):
    """Stops (pauses) the simulation."""
    await simulator.stop()
    return {'message': 'Simulation paused'}


@router.post("/reset")
async def reset_simulation(simulator: Simulator = Depends(get_simulator)):
    """Resets the simulation and clears device location overrides."""
    await simulator.reset()
    return {'message': 'Simulation reset and location cleared'}


@router.get("/status")
async def get_status(simulator: Simulator = Depends(get_simulator)):
    """Real-time simulation status (HTTP polling fallback)."""
    return simulator.status
