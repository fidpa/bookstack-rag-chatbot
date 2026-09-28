"""Timestamps in the configured zone (TZ)."""

from datetime import datetime

from config import app_timezone


def format_for_database() -> str:
    """Current time as ISO 8601 with offset, e.g. "2026-09-28T14:12:06+02:00"."""
    return datetime.now(app_timezone()).isoformat(timespec="seconds")
