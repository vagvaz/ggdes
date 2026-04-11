"""Logging configuration for GGDes using loguru."""

import sys
from pathlib import Path
from typing import Any

from loguru import logger

# Remove default handler
logger.remove()

# Add console handler with nice formatting
logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO",
    colorize=True,
)


def setup_file_logging(log_path: Path) -> None:
    """Setup file logging for an analysis.

    Args:
        log_path: Path to log file
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger.add(
        str(log_path),
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        level="DEBUG",
        rotation="10 MB",
        retention="1 week",
        encoding="utf-8",
    )

    logger.info(f"File logging enabled: {log_path}")


def get_logger(name: str) -> Any:
    """Get a logger instance with the specified name.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Logger instance
    """
    return logger.bind(name=name)


__all__ = ["logger", "setup_file_logging", "get_logger"]
