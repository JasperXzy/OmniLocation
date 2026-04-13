"""Shared FastAPI dependencies for accessing app.state singletons."""

from fastapi import Request

from core.device_manager import DevicePool
from core.simulator import Simulator


def get_device_pool(request: Request) -> DevicePool:
    """Returns the shared DevicePool stored on app.state."""
    return request.app.state.device_pool


def get_simulator(request: Request) -> Simulator:
    """Returns the shared Simulator stored on app.state."""
    return request.app.state.simulator
