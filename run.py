"""Entry point for the OmniLocation Server.

Starts the background asyncio loop for device simulation and the Flask
web server for user interaction. Configuration is loaded from .env file.
"""

import asyncio
import logging
import os
import threading

from dotenv import load_dotenv

from core.device_manager import DevicePool
from core.logger import setup_logging
from core.simulator import Simulator
from web.app import create_app

# Load environment variables from .env file
load_dotenv()

# Configure logging with rotation
setup_logging(
    log_dir="logs",
    log_filename="omni_web.log",
    max_bytes=10*1024*1024,  # 10MB
    backup_count=5
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

    Initializes core components, starts the background asyncio thread,
    and runs the Flask web server using configuration from environment variables.
    """
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
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 5005))
    
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
