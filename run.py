"""Entry point for the OmniLocation Server (FastAPI).

Starts the Uvicorn server which hosts the FastAPI application.
Configuration is loaded from .env file.
"""

import logging
import os
import uvicorn
from dotenv import load_dotenv

from core.logger import setup_logging
from web.app import create_app

# Load environment variables
load_dotenv()

# Configure logging
setup_logging(
    log_dir="logs",
    log_filename="omni_web.log",
    max_bytes=10*1024*1024,
    backup_count=5
)
logger = logging.getLogger(__name__)

def main() -> None:
    """Main execution function."""
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 5005))
    
    logger.info("Starting OmniLocation Server (FastAPI) at http://%s:%d", host, port)
    
    app = create_app()
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
    )

if __name__ == "__main__":
    main()
