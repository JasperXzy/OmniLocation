"""Entry point for the OmniLocation Server.

Starts the background asyncio loop for device simulation and the Flask
web server for user interaction.
"""

import argparse
import asyncio
import logging
import threading
from typing import NoReturn

from core.device_manager import DevicePool
from core.simulator import Simulator
from web.app import create_app

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Runs the asyncio event loop forever.

    Args:
        loop: The asyncio event loop to run.
    """
    asyncio.set_event_loop(loop)
    loop.run_forever()


def main() -> None:
    """Main execution function.

    Parses arguments, initializes core components, starts the background
    asyncio thread, and runs the Flask web server.
    """
    parser = argparse.ArgumentParser(description="OmniLocation Server")
    parser.add_argument(
        '-p', '--port', type=int, default=5005, help="Port to run the server on"
    )
    parser.add_argument(
        '--host', type=str, default="0.0.0.0", help="Host to bind to"
    )
    args = parser.parse_args()

    # 1. Setup Asyncio Loop in a Background Thread
    bg_loop = asyncio.new_event_loop()
    t = threading.Thread(target=run_loop, args=(bg_loop,), daemon=True)
    t.start()
    logger.info("Background asyncio loop started.")

    # 2. Initialize Core Components
    device_pool = DevicePool()
    simulator = Simulator(device_pool)

    # 3. Create Web App
    app = create_app(device_pool, simulator, bg_loop)

    # 4. Run Flask (Blocking)
    host = args.host
    port = args.port
    logger.info("Starting Web UI at http://%s:%d", host, port)
    
    try:
        # use_reloader=False is important when using background threads
        # to avoid duplicates
        app.run(host=host, port=port, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        pass
    finally:
        logger.info("Shutting down...")
        # Clean up async loop
        bg_loop.call_soon_threadsafe(bg_loop.stop)
        t.join()


if __name__ == "__main__":
    main()
