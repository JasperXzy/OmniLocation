"""Manages the location simulation loop and device coordination."""

import asyncio
import logging
import random
from typing import Any, Dict, List, Optional

from core.device_manager import DevicePool, IOSDevice
from core.exceptions import (
    SimulationAlreadyRunningError,
    SimulationNotRunningError,
    NoDevicesAvailableError,
    DeviceConnectionError,
)

logger = logging.getLogger(__name__)


class Simulator:
    """Controls the simulation lifecycle and broadcasts coordinates to devices.

    Handles the asynchronous loop that iterates through GPX points, calculates
    timing delays, applies jitter, and updates connected devices.

    Attributes:
        device_pool: The pool of managed devices.
        active: Boolean flag indicating if the simulation is currently running.
        current_task: The asyncio.Task object for the running simulation loop.
        status: A dictionary containing realtime simulation metrics.
    """

    def __init__(self, device_pool: DevicePool) -> None:
        """Initializes the Simulator.

        Args:
            device_pool: An instance of DevicePool containing available devices.
        """
        self.device_pool = device_pool
        self.active: bool = False
        self.current_task: Optional[asyncio.Task] = None
        self._active_devices: List[IOSDevice] = []  # Track active devices
        self.status: Dict[str, Any] = {
            "running": False,
            "current_index": 0,
            "total_points": 0,
            "speed_multiplier": 1.0,
            "loop": False,
            "current_lat": None,
            "current_lon": None,
        }

    async def start(
        self,
        points: List[Dict[str, Any]],
        udids: List[str],
        loop_track: bool = False,
        speed_multiplier: float = 1.0,
        target_duration: Optional[float] = None,
    ) -> None:
        """Starts the simulation loop for selected devices.

        Args:
            points: A list of dicts representing track points (lat, lon, time).
            udids: A list of unique device identifiers to include in the simulation.
            loop_track: If True, restarts the track from the beginning upon completion.
            speed_multiplier: Factor to adjust playback speed (e.g., 2.0 is 2x speed).
            target_duration: Total desired duration in seconds (optional).
                             Used as fallback if points lack timestamps.
        
        Raises:
            SimulationAlreadyRunningError: If simulation is already active.
            NoDevicesAvailableError: If no valid devices are available.
        """
        if self.active:
            logger.warning("Simulation is already running.")
            raise SimulationAlreadyRunningError()

        self._active_devices = []  # Reset active devices list
        for udid in udids:
            dev = self.device_pool.get_device(udid)
            if dev:
                if not dev.connected:
                    try:
                        await dev.connect()
                    except Exception as e:
                        logger.error("Could not connect to %s, skipping. Error: %s", udid, e)
                        raise DeviceConnectionError(udid, str(e))
                self._active_devices.append(dev)
            else:
                logger.warning("Device %s not found in pool.", udid)

        if not self._active_devices:
            logger.error("No valid devices available for simulation.")
            raise NoDevicesAvailableError()

        self.active = True
        self._update_status(
            running=True,
            total_points=len(points),
            loop=loop_track,
            speed_multiplier=speed_multiplier,
            current_lat=points[0]['lat'] if points else None,
            current_lon=points[0]['lon'] if points else None,
        )

        self.current_task = asyncio.create_task(
            self._run_loop(points, self._active_devices, loop_track, speed_multiplier, target_duration)
        )
        logger.info("Simulation started for %d devices.", len(self._active_devices))

    async def stop(self) -> None:
        """Stops the currently running simulation (pauses)."""
        self.active = False
        self._update_status(running=False)
        
        if self.current_task:
            self.current_task.cancel()
            try:
                await self.current_task
            except asyncio.CancelledError:
                pass
            self.current_task = None
        logger.info("Simulation stopped (paused).")

    async def reset(self) -> None:
        """Stops simulation and restores real location on all devices."""
        await self.stop()
        
        logger.info("Resetting locations for %d devices...", len(self._active_devices))
        for dev in self._active_devices:
            try:
                dev.disconnect() # This clears the location override
            except Exception as e:
                logger.error("Error resetting device %s: %s", dev.udid, e)
        
        self._active_devices = []
        self._update_status(
            current_index=0,
            current_lat=None,
            current_lon=None
        )
        logger.info("Simulation reset complete.")

    def _update_status(self, **kwargs: Any) -> None:
        """Helper to update the status dictionary."""
        self.status.update(kwargs)

    async def _run_loop(
        self,
        points: List[Dict[str, Any]],
        devices: List[IOSDevice],
        loop_track: bool,
        speed_multiplier: float,
        target_duration: Optional[float] = None,
    ) -> None:
        """Internal main loop for the simulation.

        Args:
            points: List of GPX points.
            devices: List of target IOSDevice objects.
            loop_track: Whether to loop.
            speed_multiplier: Speed adjustment factor.
            target_duration: Fallback duration if timestamps are missing.
        """
        try:
            # Check if we have valid timestamps
            has_timestamps = all(p.get("time") for p in points)
            
            # Calculate constant delay for no-timestamp case
            constant_delay = 1.0
            if not has_timestamps and target_duration and len(points) > 1:
                 constant_delay = target_duration / len(points)
            elif not has_timestamps:
                 logger.warning("No timestamps and no target_duration. Defaulting to 1.0s delay.")

            while self.active:
                for i, point in enumerate(points):
                    if not self.active:
                        break

                    lat, lon = point["lat"], point["lon"]
                    self.status["current_index"] = i
                    self.status["current_lat"] = lat
                    self.status["current_lon"] = lon

                    # Broadcast location with simple jitter
                    # TODO(Future): Move jitter logic to a separate helper or config.
                    for dev in devices:
                        jitter_lat = lat + random.uniform(-0.00002, 0.00002)
                        jitter_lon = lon + random.uniform(-0.00002, 0.00002)
                        dev.set_location(jitter_lat, jitter_lon)

                    # Calculate sleep time
                    sleep_time = constant_delay

                    if has_timestamps and i < len(points) - 1:
                        curr_time = points[i]["time"]
                        next_time = points[i + 1]["time"]
                        if curr_time and next_time:
                            delta = (next_time - curr_time).total_seconds()
                            sleep_time = delta / speed_multiplier
                    
                    # Clamp sleep time to reasonable bounds
                    if sleep_time > 300:
                        sleep_time = 5.0
                    elif sleep_time < 0:
                        sleep_time = 0.0

                    await asyncio.sleep(sleep_time)

                if not loop_track:
                    break

        except Exception as e:
            logger.error("Simulation loop encountered an error: %s", e)
        finally:
            self.active = False
            self.status["running"] = False
