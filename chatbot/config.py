"""Application configuration and timezone-aware log formatting."""

import os
import logging
import pytz
from datetime import datetime


class TimezoneFormatter(logging.Formatter):
    """Custom Formatter für Logs mit lokaler Zeitzone (Europe/Berlin)"""

    def __init__(self, fmt=None, datefmt=None):
        super().__init__(fmt, datefmt)
        self.timezone = pytz.timezone("Europe/Berlin")

    def formatTime(self, record, datefmt=None):
        """Override um lokale Zeitzone zu verwenden"""
        dt = datetime.fromtimestamp(record.created, self.timezone)
        if datefmt:
            return dt.strftime(datefmt)
        # Standard Format mit Zeitzone
        return dt.strftime("%Y-%m-%d %H:%M:%S %Z")


def setup_logging():
    """Configure timezone-aware logging for all application modules."""
    # Custom Formatter mit lokaler Zeit
    formatter = TimezoneFormatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # Root Logger konfigurieren
    root_logger = logging.getLogger()

    # Entferne bestehende Handler um Duplikate zu vermeiden
    if root_logger.handlers:
        for handler in root_logger.handlers.copy():
            root_logger.removeHandler(handler)

    root_logger.addHandler(console_handler)
    root_logger.setLevel(logging.INFO)

    # Spezifische Logger
    logging.getLogger("werkzeug").setLevel(logging.INFO)
    logging.getLogger("bookstack").setLevel(logging.INFO)
    logging.getLogger("chat").setLevel(logging.INFO)


class Config:
    """Base configuration"""

    SECRET_KEY = (
        os.environ.get("SECRET_KEY") or "chatbot-dev-secret-change-in-production"
    )
    DATABASE_PATH = os.environ.get("DATABASE_PATH") or os.path.join(
        os.path.dirname(__file__), "data", "chatbot.db"
    )
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file uploads

    # LLM Configuration (Anthropic removed - using Azure OpenAI only)

    # Widget-Only Configuration: Email & Feature flags removed
    # BookStack handles authentication and features


class DevelopmentConfig(Config):
    """Development configuration"""

    DEBUG = True
    TESTING = False


class ProductionConfig(Config):
    """Production configuration"""

    DEBUG = False
    TESTING = False
    SECRET_KEY = os.environ.get("SECRET_KEY") or "change-this-in-production"


class TestingConfig(Config):
    """Testing configuration"""

    TESTING = True
    DATABASE_PATH = ":memory:"  # In-memory database for tests


# Configuration mapping
config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}

# Widget-Only: No feature flags needed - removed for simplicity
