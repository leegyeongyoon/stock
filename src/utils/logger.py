"""Logging configuration using loguru."""

import sys
from pathlib import Path

from loguru import logger

from src.config.settings import settings


def setup_logger() -> None:
    """Configure loguru logger."""
    logger.remove()

    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )

    logger.add(
        sys.stderr,
        format=log_format,
        level=settings.log_level,
        colorize=True,
    )

    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    logger.add(
        log_dir / "stock_trading_{time:YYYY-MM-DD}.log",
        format=log_format,
        level="DEBUG",
        rotation="00:00",
        retention="30 days",
        compression="zip",
    )

    logger.add(
        log_dir / "errors_{time:YYYY-MM-DD}.log",
        format=log_format,
        level="ERROR",
        rotation="00:00",
        retention="90 days",
    )


def get_logger(name: str = __name__):
    """Get a logger instance with the given name."""
    return logger.bind(name=name)
