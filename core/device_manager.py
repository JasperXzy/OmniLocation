"""Manages device connections, interactions, and persistence via SQLite."""

import asyncio
import logging
import sqlite3
from typing import Any, Dict, List, Optional, Set, Tuple

# iOS Imports
from pymobiledevice3.exceptions import InvalidServiceError
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.remote.remote_service_discovery import RemoteServiceDiscoveryService
from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
from pymobiledevice3.services.simulate_location import DtSimulateLocation
from pymobiledevice3.usbmux import list_devices as list_ios_devices

from core.exceptions import (
    DatabaseError,
    DeviceConnectionError,
    DeviceControlError,
)

logger = logging.getLogger(__name__)

DB_PATH = "devices.db"


async def _fetch_tunnel_map() -> Dict[str, Dict[str, Any]]:
    """Fetches the current Tunneld tunnel map keyed by UDID.

    Tunneld exposes its registry over an HTTP endpoint via blocking
    ``requests``, so we always offload it to a thread. Returns an empty dict
    when Tunneld is unreachable so the caller can degrade to USB-only mode.
    """
    try:
        # pylint: disable=import-outside-toplevel, protected-access
        from pymobiledevice3.tunneld.api import _list_tunnels
        tunnels: Dict[str, list] = await asyncio.to_thread(_list_tunnels)
    except Exception as e:
        logger.debug("Tunneld not reachable: %s", e)
        return {}

    result: Dict[str, Dict[str, Any]] = {}
    for udid, entries in tunnels.items():
        if not entries:
            continue
        info = entries[0]
        if "tunnel-address" not in info or "tunnel-port" not in info:
            continue
        result[udid] = {
            "host": info["tunnel-address"],
            "port": int(info["tunnel-port"]),
            "interface": info.get("interface"),
        }
    return result


def init_db() -> None:
    """Initializes the SQLite database table if it does not exist.
    
    Raises:
        DatabaseError: If database initialization fails.
    """
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
        raise DatabaseError("initialization", str(e))


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
    
    Raises:
        DatabaseError: If database update fails.
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
        raise DatabaseError("update", str(e))


class BaseDevice:
    """Abstract base class representing a generic iOS device.

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

    async def set_location(self, lat: float, lon: float) -> None:
        """Updates the device's location.

        Args:
            lat: Latitude.
            lon: Longitude.
        """
        raise NotImplementedError

    async def disconnect(self) -> None:
        """Closes the connection to the device."""
        raise NotImplementedError


class IOSDevice(BaseDevice):
    """Represents an iOS device managed via pymobiledevice3.

    Connection model
    ----------------
    * **RSD (preferred for iOS 17+)** — when Tunneld exposes a tunnel for this
      UDID we use ``RemoteServiceDiscoveryService`` + ``DvtProvider`` +
      ``LocationSimulation``. This is the only path that works on iOS 17+ and
      it is independent of whether the device is physically wired or wireless.
    * **Legacy usbmux (iOS < 17)** — only used as a fallback when no tunnel
      exists. Opens a ``UsbmuxLockdownClient`` and the legacy
      ``com.apple.dt.simulatelocation`` service via ``DtSimulateLocation``.

    Attributes:
        serial: Device serial number (== UDID for modern usbmux).
        rsd_info: Dict with ``host``/``port``/``interface`` for the Tunneld
            tunnel, or ``None`` if the device is only reachable via usbmux.
    """

    def __init__(
        self,
        udid: str,
        serial: Optional[str] = None,
        connection_type: str = "usb",
        rsd_info: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initializes the IOSDevice.

        Args:
            udid: The unique device identifier.
            serial: The device serial number. Defaults to udid if None.
            connection_type: 'usb' or 'wifi' (display label only; the actual
                transport is decided by the presence of ``rsd_info``).
            rsd_info: Optional tunnel info dict. When set, RSD is used.
        """
        super().__init__(udid, name=f"iPhone ({udid[:8]}...)")
        self.serial = serial or udid
        self.connection_type = connection_type
        self.rsd_info = rsd_info

        self._lockdown: Any = None       # UsbmuxLockdownClient OR RSDS
        self._service: Any = None        # DtSimulateLocation OR LocationSimulation
        self._dvt_context: Any = None    # DvtProvider (RSD path only)
        self._location_ctx: Any = None   # LocationSimulation context handle

    async def connect(self) -> None:
        """Connects to the iOS device and fetches its real name.

        Picks RSD when ``rsd_info`` is set, otherwise falls back to legacy
        usbmux. Cleans up any partially-opened resources on failure.

        Raises:
            DeviceConnectionError: If connection fails.
        """
        try:
            if self.rsd_info is not None:
                await self._connect_rsd()
            else:
                await self._connect_usb()

            self.connected = True
            logger.info(
                "Device %s connected via %s",
                self.udid,
                "RSD" if self.rsd_info else "usbmux",
            )

            await self._fetch_device_name()

        except Exception as e:
            logger.error("Failed to connect to %s: %s", self.udid, e)
            await self._teardown()
            raise DeviceConnectionError(self.udid, str(e))

    async def _connect_rsd(self) -> None:
        """Opens RSD → DvtProvider → LocationSimulation."""
        assert self.rsd_info is not None
        host = self.rsd_info["host"]
        port = self.rsd_info["port"]
        interface = self.rsd_info.get("interface")
        logger.info(
            "Connecting via RSD: %s:%s (iface=%s)", host, port, interface,
        )

        rsd = RemoteServiceDiscoveryService((host, port), name=interface)
        await rsd.connect()
        self._lockdown = rsd

        self._dvt_context = DvtProvider(rsd)
        await self._dvt_context.__aenter__()

        self._location_ctx = LocationSimulation(self._dvt_context)
        await self._location_ctx.__aenter__()
        self._service = self._location_ctx

    async def _connect_usb(self) -> None:
        """Opens a usbmux lockdown + legacy DtSimulateLocation service.

        Only viable for iOS < 17. On iOS 17+ this raises
        ``DeviceConnectionError`` with a hint to start Tunneld.
        """
        logger.info("Connecting via usbmux: %s", self.serial)
        self._lockdown = await create_using_usbmux(serial=self.serial)

        try:
            # DtSimulateLocation.__init__ is sync (just opens a lockdown service)
            self._service = DtSimulateLocation(self._lockdown)
        except InvalidServiceError as e:
            raise DeviceConnectionError(
                self.udid,
                "Legacy simulate-location service unavailable (iOS 17+ "
                "requires Tunneld). Start `pymobiledevice3 remote tunneld` "
                "and rescan.",
            ) from e

    async def _fetch_device_name(self) -> None:
        """Fetches the device name from lockdown / RSD ``get_value``."""
        if self._lockdown is None:
            return
        try:
            val = await self._lockdown.get_value(key="DeviceName")
            if val:
                name_str = str(val)
                self.real_name = name_str
                await asyncio.to_thread(
                    update_device_info_in_db, self.udid, real_name=name_str,
                )
                logger.info("Fetched real name for %s: %s", self.udid, name_str)
        except Exception as e:
            logger.warning("Could not fetch device name for %s: %s", self.udid, e)

    async def set_location(self, lat: float, lon: float) -> None:
        """Sets the simulated location on the device.

        Args:
            lat: Latitude.
            lon: Longitude.

        Raises:
            DeviceControlError: If setting location fails.
        """
        if not self._service:
            raise DeviceControlError(self.udid, "set location", "Service not available")

        try:
            await self._service.set(lat, lon)
        except Exception as e:
            logger.error("Error setting location for %s: %s", self.udid, e)
            self.connected = False
            raise DeviceControlError(self.udid, "set location", str(e))

    async def disconnect(self) -> None:
        """Stops simulation and closes any connections we opened."""
        # Best-effort clear() so the device drops the location override.
        if self._service is not None:
            try:
                await self._service.clear()
            except Exception as e:
                logger.debug("clear() failed for %s: %s", self.udid, e)
        await self._teardown()
        self.connected = False

    async def _teardown(self) -> None:
        """Idempotent cleanup of RSD / DVT / lockdown resources."""
        # 1. LocationSimulation (RSD path is an async ctx manager)
        if self._location_ctx is not None:
            try:
                await self._location_ctx.__aexit__(None, None, None)
            except Exception as e:
                logger.debug("LocationSimulation aexit failed: %s", e)
            self._location_ctx = None

        # 2. DvtProvider (RSD path only)
        if self._dvt_context is not None:
            try:
                await self._dvt_context.__aexit__(None, None, None)
            except Exception as e:
                logger.debug("DvtProvider aexit failed: %s", e)
            self._dvt_context = None

        # 3. Lockdown / RSD socket
        if self._lockdown is not None:
            try:
                await self._lockdown.close()
            except Exception as e:
                logger.debug("lockdown.close failed: %s", e)
            self._lockdown = None

        self._service = None


class DevicePool:
    """Manages a collection of connected iOS devices."""

    def __init__(self) -> None:
        self.devices: Dict[str, BaseDevice] = {}
        init_db()

    async def scan_usb_devices(self) -> List[BaseDevice]:
        """Discovers iOS devices via Tunneld AND usbmux, returning the union.

        Devices reachable via Tunneld are preferred (RSD path) regardless of
        whether they are also visible to usbmuxd, since RSD is the only
        viable route on iOS 17+.
        """
        # 1. Discover both sources concurrently.
        tunnel_task = asyncio.create_task(_fetch_tunnel_map())
        usbmux_task = asyncio.create_task(list_ios_devices())
        try:
            tunnel_map = await tunnel_task
        except Exception as e:
            logger.warning("Tunneld discovery failed: %s", e)
            tunnel_map = {}
        try:
            mux_devices = await usbmux_task
        except Exception as e:
            logger.warning("usbmux discovery failed: %s", e)
            mux_devices = []

        # 2. Build a UDID → (serial, source) map so we can union both sources.
        mux_by_udid: Dict[str, Any] = {}
        for d in mux_devices:
            mux_by_udid[d.serial] = d

        all_udids: Set[str] = set(tunnel_map.keys()) | set(mux_by_udid.keys())
        if not all_udids:
            logger.debug("No iOS devices found via Tunneld or usbmux")

        # 3. Materialize devices, preferring RSD whenever a tunnel exists.
        found_devices: List[BaseDevice] = []
        for udid in all_udids:
            rsd_info = tunnel_map.get(udid)
            mux_dev = mux_by_udid.get(udid)
            serial = mux_dev.serial if mux_dev is not None else udid
            conn_type = "wifi" if rsd_info else "usb"

            existing = self.devices.get(udid)
            if existing is None or not isinstance(existing, IOSDevice):
                new_dev = IOSDevice(
                    udid=udid,
                    serial=serial,
                    connection_type=conn_type,
                    rsd_info=rsd_info,
                )
                self.devices[udid] = new_dev
                found_devices.append(new_dev)
                continue

            # Existing record — refresh transport metadata. If the connection
            # parameters changed (e.g. tunneld came up while we were already
            # holding a usbmux client), drop the stale connection so the next
            # start() reconnects via the new path.
            params_changed = (existing.rsd_info != rsd_info)
            if params_changed and existing.connected:
                logger.info(
                    "Transport for %s changed (rsd=%s); dropping stale connection",
                    udid, bool(rsd_info),
                )
                try:
                    await existing.disconnect()
                except Exception as e:
                    logger.debug("Stale-disconnect failed for %s: %s", udid, e)

            existing.rsd_info = rsd_info
            existing.connection_type = conn_type
            existing.serial = serial
            existing.real_name, existing.custom_name = get_device_info_from_db(udid)
            found_devices.append(existing)

        return found_devices

    def get_device(self, udid: str) -> Optional[BaseDevice]:
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

    def get_all_devices(self) -> List[BaseDevice]:
        """Returns a list of all managed devices."""
        return list(self.devices.values())
