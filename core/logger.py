import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Optional

def setup_logging(
    log_dir: str = "logs",
    log_filename: str = "omni_app.log",
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5,
    log_level: int = logging.INFO
) -> None:
    """Configures the root logger with rotating file and stream handlers.

    Args:
        log_dir: Directory to store log files.
        log_filename: Name of the log file.
        max_bytes: Maximum size in bytes before rotating.
        backup_count: Number of backup files to keep.
        log_level: Logging level (default: logging.INFO).
    """
    # Ensure log directory exists
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, log_filename)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove existing handlers to avoid duplicates if called multiple times
    if root_logger.handlers:
        root_logger.handlers.clear()

    # 1. Rotating File Handler
    # Rotates logs when they reach max_bytes. Keeps backup_count old files.
    file_handler = RotatingFileHandler(
        log_path, 
        maxBytes=max_bytes, 
        backupCount=backup_count,
        encoding='utf-8'
    )
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    # 2. Stream Handler (Console)
    # Writes to stderr so it can still be captured by systemd/launchd if needed
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    )
    stream_handler.setFormatter(stream_formatter)
    root_logger.addHandler(stream_handler)

    logging.info(f"Logging configured. Log file: {log_path}")
