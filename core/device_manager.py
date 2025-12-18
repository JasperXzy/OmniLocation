"""Manages device connections, interactions, and persistence via SQLite."""

import asyncio
import logging
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from pymobiledevice3.exceptions import InvalidServiceError
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.remote.remote_service_discovery import RemoteServiceDiscoveryService
from pymobiledevice3.services.dvt.dvt_secure_socket_proxy import DvtSecureSocketProxyService
from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
from pymobiledevice3.services.simulate_location import DtSimulateLocation
from pymobiledevice3.usbmux import list_devices

logger = logging.getLogger(__name__)

DB_PATH = "devices.db"


def init_db() -> None:
    """Initializes the SQLite database table if it does not exist."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS devices (
                    udid TEXT PRIMARY KEY,
                    real_name TEXT,
                    custom_name TEXT,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()
    except sqlite3.Error as e:
        logger.error("Failed to initialize database: %s", e)


def get_device_info_from_db(udid: str) -> Tuple[Optional[str], Optional[str]]:
    """Retrieves real_name and custom_name from the database.

    Args:
        udid: The Unique Device Identifier.

    Returns:
        A tuple containing (real_name, custom_name).
        Values can be None if not found.
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute(
                "SELECT real_name, custom_name FROM devices WHERE udid = ?", (udid,)
            )
            row = cursor.fetchone()
            if row:
                return row[0], row[1]
    except sqlite3.Error as e:
        logger.error("Database error retrieving info for %s: %s", udid, e)
    return None, None


def update_device_info_in_db(
    udid: str, real_name: Optional[str] = None, custom_name: Optional[str] = None
) -> None:
    """Updates device information in the database.

    Args:
        udid: The Unique Device Identifier.
        real_name: The device's factory name (optional).
        custom_name: The user-assigned name (optional).
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            # Check if record exists
            cursor = conn.execute("SELECT 1 FROM devices WHERE udid = ?", (udid,))
            exists = cursor.fetchone()

            if exists:
                if real_name is not None:
                    conn.execute(
                        "UPDATE devices SET real_name = ?, last_seen = CURRENT_TIMESTAMP WHERE udid = ?",
                        (real_name, udid),
                    )
                if custom_name is not None:
                    conn.execute(
                        "UPDATE devices SET custom_name = ?, last_seen = CURRENT_TIMESTAMP WHERE udid = ?",
                        (custom_name, udid),
                    )
            else:
                conn.execute(
                    "INSERT INTO devices (udid, real_name, custom_name) VALUES (?, ?, ?)",
                    (udid, real_name, custom_name),
                )
            conn.commit()
    except sqlite3.Error as e:
        logger.error("Database error updating info for %s: %s", udid, e)


class BaseDevice:
    """Abstract base class representing a generic mobile device.

    Attributes:
        udid: The Unique Device Identifier.
        connected: Connection status flag.
        connection_type: Type of connection ('usb', 'wifi', or 'unknown').
        real_name: Name retrieved from the device hardware.
        custom_name: Name assigned by the user.
    """

    def __init__(self, udid: str, name: str = "Unknown") -> None:
        """Initializes the BaseDevice and loads persisted names."""
        self.udid = udid
        self._default_name = name
        self.connected = False
        self.connection_type = "unknown"
        
        self.real_name: Optional[str] = None
        self.custom_name: Optional[str] = None

        # Load persisted names
        self.real_name, self.custom_name = get_device_info_from_db(udid)

    @property
    def name(self) -> str:
        """Returns the display name (Custom > Real > Default)."""
        if self.custom_name:
            return self.custom_name
        if self.real_name:
            return self.real_name
        return self._default_name

    async def connect(self) -> None:
        """Establishes a connection to the device."""
        raise NotImplementedError

    def set_location(self, lat: float, lon: float) -> None:
        """Updates the device's location.

        Args:
            lat: Latitude.
            lon: Longitude.
        """
        raise NotImplementedError

    def disconnect(self) -> None:
        """Closes the connection to the device."""
        raise NotImplementedError


class IOSDevice(BaseDevice):
    """Represents an iOS device managed via pymobiledevice3.

    Supports both legacy USB connections and iOS 17+ RSD (Remote Service Discovery)
    connections over Tunneld.

    Attributes:
        serial: Device serial number (often same as UDID).
        rsd_info: Tuple of (host, port) for RSD connections, if available.
    """

    def __init__(
        self,
        udid: str,
        serial: Optional[str] = None,
        connection_type: str = "usb",
        rsd_info: Optional[Tuple[str, int]] = None,
    ) -> None:
        """Initializes the IOSDevice.

        Args:
            udid: The unique device identifier.
            serial: The device serial number. Defaults to udid if None.
            connection_type: 'usb' or 'wifi'.
            rsd_info: Optional tuple (host, port) for RSD connections.
        """
        super().__init__(udid, name=f"iPhone ({udid[:8]}...)")
        self.serial = serial or udid
        self.connection_type = connection_type
        self.rsd_info = rsd_info

        self._lockdown: Any = None
        self._service: Any = None
        self._dvt_context: Any = None

    async def connect(self) -> None:
        """Connects to the iOS device and attempts to fetch its real name.

        Raises:
            Exception: If connection fails.
        """
        try:
            if self.connection_type == "wifi" and self.rsd_info:
                await self._connect_rsd()
            else:
                self._connect_usb()
            
            self.connected = True
            logger.info("Device %s connected via %s", self.udid, self.connection_type)
            
            # Fetch real name after successful connection
            self._fetch_device_name()

        except Exception as e:
            self.connected = False
            logger.error("Failed to connect to %s: %s", self.udid, e)
            raise

    def _fetch_device_name(self) -> None:
        """Fetches the device name from the Lockdown service."""
        try:
            if self._lockdown:
                val = self._lockdown.get_value(key="DeviceName")
                if val:
                    name_str = str(val)
                    self.real_name = name_str
                    update_device_info_in_db(self.udid, real_name=name_str)
                    logger.info("Fetched real name for %s: %s", self.udid, name_str)
        except Exception as e:
            logger.warning("Could not fetch device name for %s: %s", self.udid, e)

    async def _connect_rsd(self) -> None:
        """Internal method to connect via Remote Service Discovery (RSD)."""
        if not self.rsd_info:
            raise ValueError("RSD info is missing.")
        
        host, port = self.rsd_info
        logger.info("Connecting via RSD: %s:%s", host, port)
        
        rsd = RemoteServiceDiscoveryService((host, int(port)))
        await rsd.connect()

        self._lockdown = rsd
        self._dvt_context = DvtSecureSocketProxyService(rsd)
        self._dvt_context.__enter__()
        self._service = LocationSimulation(self._dvt_context)

    def _connect_usb(self) -> None:
        """Internal method to connect via standard USB mux."""
        logger.info("Connecting via USB: %s", self.serial)
        self._lockdown = create_using_usbmux(serial=self.serial)

        # Try legacy service first, then DVT
        try:
            self._service = DtSimulateLocation(self._lockdown)
        except InvalidServiceError:
            logger.info("DtSimulateLocation not available, trying DVT...")
            self._dvt_context = DvtSecureSocketProxyService(self._lockdown)
            self._dvt_context.__enter__()
            self._service = LocationSimulation(self._dvt_context)

    def set_location(self, lat: float, lon: float) -> None:
        """Sets the simulated location on the device.

        Args:
            lat: Latitude.
            lon: Longitude.
        """
        if not self._service:
            return
        try:
            self._service.set(lat, lon)
        except Exception as e:
            logger.error("Error setting location for %s: %s", self.udid, e)
            self.connected = False

    def disconnect(self) -> None:
        """Stops simulation and closes connections."""
        if self._service:
            try:
                self._service.clear()
            except Exception:
                pass

        if self._dvt_context:
            try:
                self._dvt_context.__exit__(None, None, None)
            except Exception:
                pass
        self.connected = False


class DevicePool:
    """Manages a collection of connected devices."""

    def __init__(self) -> None:
        self.devices: Dict[str, IOSDevice] = {}
        init_db()

    def scan_usb_devices(self) -> List[IOSDevice]:
        """Scans for connected devices via USB and Tunneld."""
        found_devices: List[IOSDevice] = []
        
        # 1. Scan Standard USB Devices
        usb_devices = list_devices()

        # 2. Scan Tunneld Devices (iOS 17+)
        tunnel_map: Dict[str, Tuple[str, int]] = {}
        try:
            # pylint: disable=import-outside-toplevel, protected-access
            from pymobiledevice3.tunneld.api import _list_tunnels
            tunnels_dict = _list_tunnels()

            for t_udid, t_list in tunnels_dict.items():
                if t_list:
                    tunnel_info = t_list[0]
                    if "tunnel-address" in tunnel_info and "tunnel-port" in tunnel_info:
                        tunnel_map[t_udid] = (
                            tunnel_info["tunnel-address"],
                            tunnel_info["tunnel-port"],
                        )
        except Exception:
            # Ignore tunneld errors during scan
            pass

        # Process devices
        for dev in usb_devices:
            udid = dev.serial
            rsd_info = tunnel_map.get(udid)
            conn_type = "wifi" if rsd_info else "usb"

            if udid not in self.devices:
                new_dev = IOSDevice(
                    udid=udid,
                    serial=dev.serial,
                    connection_type=conn_type,
                    rsd_info=rsd_info,
                )
                self.devices[udid] = new_dev
                found_devices.append(new_dev)
            else:
                existing = self.devices[udid]
                existing.rsd_info = rsd_info
                existing.connection_type = conn_type
                existing.real_name, existing.custom_name = get_device_info_from_db(udid)
                found_devices.append(existing)

        return found_devices

    def get_device(self, udid: str) -> Optional[IOSDevice]:
        """Retrieves a device by its UDID."""
        return self.devices.get(udid)
    
    def rename_device(self, udid: str, new_name: str) -> bool:
        """Sets a custom name for a device.

        Args:
            udid: The device identifier.
            new_name: The new custom name.

        Returns:
            True if successful, False if validation failed.
        """
        if not new_name.strip():
            return False
            
        update_device_info_in_db(udid, custom_name=new_name)
        
        # Update in-memory object if present
        if udid in self.devices:
            self.devices[udid].custom_name = new_name
        return True

    def get_all_devices(self) -> List[IOSDevice]:
        """Returns a list of all managed devices."""
        return list(self.devices.values())