"""Device discovery and management endpoints."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.device_manager import DevicePool
from core.exceptions import ResourceNotFoundError
from web.dependencies import get_device_pool

router = APIRouter(prefix="/api/devices", tags=["devices"])


class RenameDeviceRequest(BaseModel):
    udid: str
    name: str


@router.get("")
async def list_devices(device_pool: DevicePool = Depends(get_device_pool)):
    """Lists connected devices after triggering a scan."""
    devices = await device_pool.scan_usb_devices()
    return [
        {
            'udid': d.udid,
            'name': d.name,
            'real_name': d.real_name,
            'device_type': 'iOS' if d.__class__.__name__ == 'IOSDevice' else 'Android',
            'connection_type': d.connection_type,
            'connected': d.connected,
        }
        for d in devices
    ]


@router.post("/rename")
async def rename_device(
    req: RenameDeviceRequest,
    device_pool: DevicePool = Depends(get_device_pool),
):
    """Renames a device."""
    if device_pool.rename_device(req.udid, req.name):
        return {"message": "Device renamed successfully"}
    raise ResourceNotFoundError('Device', req.udid)
