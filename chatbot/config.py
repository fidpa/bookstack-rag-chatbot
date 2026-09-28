"""Application configuration and log formatting."""

import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from utils.database import get_db_path


def app_timezone():
    """The zone named by TZ (default UTC), used for log and sync timestamps."""
    try:
        return ZoneInfo(os.getenv("TZ") or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


class TimezoneFormatter(logging.Formatter):
    """Log formatter that prints times in the TZ zone, with its abbreviation."""

    def __init__(self, fmt=None, datefmt=None):
        super().__init__(fmt, datefmt)
        self.timezone = app_timezone()

    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, self.timezone)
        return dt.strftime(datefmt or "%Y-%m-%d %H:%M:%S %Z")


def setup_logging():
    """Configure the root logger from LOG_LEVEL (default INFO)."""
    handler = logging.StreamHandler()
    handler.setFormatter(
        TimezoneFormatter(fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )

    root_logger = logging.getLogger()
    for existing in root_logger.handlers.copy():
        root_logger.removeHandler(existing)
    root_logger.addHandler(handler)

    level = os.getenv("LOG_LEVEL", "INFO").upper()
    root_logger.setLevel(level if level in logging._nameToLevel else "INFO")


class Config:
    """Flask configuration"""

    SECRET_KEY = (
        os.environ.get("SECRET_KEY") or "chatbot-dev-secret-change-in-production"
    )
    DATABASE_PATH = get_db_path()
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max request body
    DEBUG = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true")
