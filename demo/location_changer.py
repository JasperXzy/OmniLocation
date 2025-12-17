import argparse
import logging
import random
import sys
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

try:
    import gpxpy
    from pymobiledevice3.exceptions import InvalidServiceError
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.remote.remote_service_discovery import RemoteServiceDiscoveryService
    from pymobiledevice3.services.dvt.dvt_secure_socket_proxy import DvtSecureSocketProxyService
    from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
    from pymobiledevice3.services.simulate_location import DtSimulateLocation
    from pymobiledevice3.tunneld.api import get_tunneld_devices
    from pymobiledevice3.usbmux import list_devices
except ImportError as e:
    print(f"Error: Missing dependency {e}")
    print("Please run: pip install -r requirements.txt")
    sys.exit(1)

logger = logging.getLogger(__name__)


def setup_logging():
    """
    Configure logging for the application
    """
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S',
        stream=sys.stdout,
        force=True
    )
    # Ensure unbuffered output for real-time logging
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(line_buffering=True)


class GPXHandler:
    """
    Handles parsing of GPX files to extract track points
    
    Attributes:
        file_path (Path): Path to the GPX file
        points (List[Dict[str, Any]]): Parsed track points
    """

    def __init__(self, file_path: str):
        """
        Initialize GPXHandler
        
        Args:
            file_path: Path to the GPX file
        """
        self.file_path = Path(file_path)
        self.points: List[Dict[str, Any]] = []

    def parse(self) -> List[Dict[str, Any]]:
        """
        Parse the GPX file and extract track points
        
        Returns:
            A list of track points
        """
        logger.info(f"Parsing GPX file: {self.file_path}")
        try:
            with self.file_path.open('r') as gpx_file:
                gpx = gpxpy.parse(gpx_file)

                for track in gpx.tracks:
                    for segment in track.segments:
                        for point in segment.points:
                            self.points.append({
                                'lat': point.latitude,
                                'lon': point.longitude,
                                'ele': point.elevation,
                                'time': point.time
                            })

            if not self.points:
                logger.warning(f"No track points found in {self.file_path}")
            else:
                logger.info(f"Loaded {len(self.points)} points from GPX")
            return self.points

        except FileNotFoundError:
            logger.error(f"GPX file not found: {self.file_path}")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Error parsing GPX file: {e}")
            sys.exit(1)


class DeviceManager:
    """
    Manages connection to the iOS device and location services
    
    Handles different connection methods (USB, RSD, tunneld) for various iOS versions
    """

    def __init__(self, rsd_address: Optional[str] = None, rsd_port: Optional[int] = None,
                 tunnel_udid: Optional[str] = None):
        """
        Initialize DeviceManager
        
        Args:
            rsd_address: RSD address for iOS 17+ connection
            rsd_port: RSD port for iOS 17+ connection
            tunnel_udid: UDID for tunneld connection
        """
        self.lockdown = None
        self.use_dvt = False
        self.rsd_address = rsd_address
        self.rsd_port = rsd_port
        self.tunnel_udid = tunnel_udid
        self._rsd_for_dvt = None
        self._dvt_context = None
        self._location_sim = None
        self.location_service = None  # For legacy connections

    def connect(self) -> None:
        """
        Establish connection to the iOS device using the best available method
        """
        if self.rsd_address and self.rsd_port:
            self._connect_rsd()
        elif self.tunnel_udid is not None:
            self._connect_tunneld()
        else:
            self._connect_usb()

    def _connect_rsd(self) -> None:
        """
        Connect via Remote Service Discovery (RSD) for iOS 17+
        """
        logger.info(f"Connecting via RSD: {self.rsd_address}:{self.rsd_port}...")
        try:
            from pymobiledevice3.utils import get_asyncio_loop

            rsd = RemoteServiceDiscoveryService((self.rsd_address, int(self.rsd_port)))
            get_asyncio_loop().run_until_complete(rsd.connect())

            self.lockdown = rsd
            self._rsd_for_dvt = rsd

            self._dvt_context = DvtSecureSocketProxyService(rsd)
            self._dvt_context.__enter__()
            self._location_sim = LocationSimulation(self._dvt_context)

            logger.info(f"Connected via RSD (UDID: {rsd.udid})")
            self.use_dvt = True
        except Exception as e:
            import traceback
            logger.error(f"Failed to connect via RSD: {e}")
            logger.error(traceback.format_exc())
            sys.exit(1)

    def _connect_tunneld(self) -> None:
        """
        Connect via tunneld daemon
        """
        logger.info("Attempting to connect via tunneld daemon...")
        try:
            from pymobiledevice3.exceptions import TunneldConnectionError
            devices = get_tunneld_devices()
            if not devices:
                logger.error("No devices found via tunneld daemon")
                sys.exit(1)

            rsd = devices[0] if self.tunnel_udid == '' else next(
                (d for d in devices if d.udid == self.tunnel_udid), None
            )

            if not rsd:
                logger.error(f"Device {self.tunnel_udid} not found in tunnel")
                sys.exit(1)

        except TunneldConnectionError:
            logger.error("Could not connect to tunneld daemon")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Failed to connect via tunneld: {e}")
            sys.exit(1)

    def _connect_usb(self) -> None:
        """
        Connect via USB (legacy method)
        """
        devices = list_devices()
        if not devices:
            logger.error("No iOS devices found via USB")
            sys.exit(1)

        device = devices[0]
        logger.info(f"Connecting to device: {device.serial}...")

        try:
            self.lockdown = create_using_usbmux(serial=device.serial)
            try:
                self.location_service = DtSimulateLocation(self.lockdown)
                logger.info("Connected to Location Simulation Service (DtSimulateLocation)")
            except InvalidServiceError:
                logger.info("DtSimulateLocation not available, trying DVT method...")
                self._dvt_context = DvtSecureSocketProxyService(self.lockdown)
                self._dvt_context.__enter__()
                self._location_sim = LocationSimulation(self._dvt_context)
                logger.info("Connected to Location Simulation Service (DVT)")
                self.use_dvt = True

        except InvalidServiceError as e:
            logger.error(f"Location Simulation Service not available: {e}")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            sys.exit(1)

    def update_location(self, lat: float, lon: float) -> bool:
        """
        Update the device's GPS location
        
        Args:
            lat: Latitude
            lon: Longitude
            
        Returns:
            True if successful, False otherwise
        """
        service = self._location_sim if self.use_dvt else self.location_service
        if not service:
            return False
        try:
            service.set(lat, lon)
            return True
        except Exception as e:
            logger.error(f"Failed to update location: {e}")
            return False

    def stop(self) -> None:
        """
        Stop location simulation and clean up connections
        """
        logger.info("Stopping location simulation...")
        service = self._location_sim if self.use_dvt else self.location_service
        if service:
            try:
                service.clear()
                logger.info("Location simulation stopped (restored to real GPS)")
            except Exception as e:
                logger.warning(f"Failed to clear location: {e}")

        if self._dvt_context:
            try:
                self._dvt_context.__exit__(None, None, None)
            except Exception as e:
                logger.warning(f"Failed to close DVT context: {e}")


class LocationSimulator:
    """
    Core simulation loop logic
    
    Handles the iteration over GPX points, time delays, and jitter application
    """

    def __init__(self, device_manager: DeviceManager, points: List[Dict[str, Any]]):
        """
        Initialize LocationSimulator
        
        Args:
            device_manager: The configured DeviceManager instance
            points: A list of GPX points
        """
        self.device_manager = device_manager
        self.points = points
        self.running = False

    def _add_jitter(self, value: float, strength: float = 0.00002) -> float:
        """
        Add random noise to a coordinate value for anti-cheat purposes
        
        Args:
            value: The coordinate value
            strength: The magnitude of the random noise
            
        Returns:
            The coordinate value with added jitter
        """
        return value + random.uniform(-strength, strength)

    def _calculate_sleep_time(self, current_point_idx: int) -> float:
        """
        Calculate the time to wait before moving to the next point
        
        Args:
            current_point_idx: The index of the current point in the list
            
        Returns:
            The sleep time in seconds
        """
        if current_point_idx < len(self.points) - 1:
            current_time = self.points[current_point_idx]['time']
            next_time = self.points[current_point_idx + 1]['time']
            if current_time and next_time:
                delta = (next_time - current_time).total_seconds()
                if 0 < delta < 300:
                    return delta
                elif delta >= 300:
                    logger.warning(f"Large time gap ({delta}s), capping at 5s")
                    return 5.0
        return 1.0  # Default fallback

    def run(self, loop: bool = False, use_jitter: bool = True) -> None:
        """
        Start the simulation loop
        
        Args:
            loop: Whether to loop the track indefinitely
            use_jitter: Whether to apply random jitter to coordinates
        """
        self.running = True
        logger.info("Starting simulation...")

        try:
            while self.running:
                for i, point in enumerate(self.points):
                    lat = self._add_jitter(point['lat'], strength=0.00002) if use_jitter else point['lat']
                    lon = self._add_jitter(point['lon'], strength=0.00002) if use_jitter else point['lon']

                    self.device_manager.update_location(lat, lon)

                    sleep_time = self._calculate_sleep_time(i)
                    logger.info(f"Point {i + 1}/{len(self.points)} -> "
                                f"Lat: {lat:.6f}, Lon: {lon:.6f} | "
                                f"Sleep: {sleep_time:.2f}s")

                    # Refresh position periodically to prevent drift
                    self._sleep_with_refresh(sleep_time, lat, lon)

                if not loop:
                    logger.info("Route completed")
                    break
                else:
                    logger.info("Route completed. Looping...")
        except KeyboardInterrupt:
            logger.info("\nSimulation interrupted by user")
        finally:
            self.device_manager.stop()

    def _sleep_with_refresh(self, total_sleep_time: float, lat: float, lon: float) -> None:
        """
        Sleep for a given duration while periodically refreshing the location
        
        Args:
            total_sleep_time: The total time to sleep
            lat: The latitude to refresh
            lon: The longitude to refresh
        """
        refresh_interval = 0.5
        elapsed = 0
        while elapsed < total_sleep_time:
            wait_time = min(refresh_interval, total_sleep_time - elapsed)
            time.sleep(wait_time)
            elapsed += wait_time
            if elapsed < total_sleep_time:
                self.device_manager.update_location(lat, lon)


def main():
    """
    Main function to parse arguments and run the simulator
    """
    setup_logging()
    
    parser = argparse.ArgumentParser(description="iOS Running Simulator")
    parser.add_argument("gpx_file", help="Path to the .gpx file")
    parser.add_argument("--loop", action="store_true", help="Loop the track indefinitely")
    parser.add_argument("--no-jitter", action="store_true", help="Disable anti-cheat random jitter")
    parser.add_argument("--tunnel", nargs='?', const='', metavar='UDID',
                        help="Connect via tunneld (for iOS >= 17). Use empty string for first device.")
    parser.add_argument("--rsd", nargs=2, metavar=('ADDRESS', 'PORT'),
                        help="Connect via RSD address and port (for iOS >= 17)")
    
    args = parser.parse_args()

    gpx_handler = GPXHandler(args.gpx_file)
    points = gpx_handler.parse()

    rsd_address = args.rsd[0] if args.rsd else None
    rsd_port = int(args.rsd[1]) if args.rsd else None
    
    device_mgr = DeviceManager(rsd_address=rsd_address, rsd_port=rsd_port,
                               tunnel_udid=args.tunnel)
    device_mgr.connect()

    sim = LocationSimulator(device_mgr, points)
    sim.run(loop=args.loop, use_jitter=not args.no_jitter)


if __name__ == "__main__":
    main()
