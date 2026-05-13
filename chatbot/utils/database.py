"""SQLite database utilities (connections, pragmas, initial schema)."""

import sqlite3
import os
import logging
from contextlib import contextmanager
from config import Config

logger = logging.getLogger(__name__)


def _apply_performance_pragmas(conn):
    """
    Apply SQLite performance optimizations for Widget Backend
    Based on 2024/2025 best practices for low-latency chat applications
    """
    try:
        cursor = conn.cursor()

        # WAL Mode FIRST - enables concurrent reads/writes (Production Best Practice 2025)
        cursor.execute("PRAGMA journal_mode = WAL")

        # Performance Pragmas for Widget Backend
        performance_pragmas = [
            "PRAGMA synchronous = NORMAL",  # Better write performance (was FULL)
            "PRAGMA temp_store = MEMORY",  # Temp tables/indexes in memory
            "PRAGMA cache_size = -8000",  # 8MB cache (was 2MB)
            "PRAGMA mmap_size = 268435456",  # 256MB memory mapping
            "PRAGMA busy_timeout = 5000",  # 5 second timeout (keep current)
        ]

        for pragma in performance_pragmas:
            cursor.execute(pragma)

        logger.debug(
            "SQLite performance pragmas applied successfully (WAL mode enabled)"
        )

    except Exception as e:
        logger.warning(f"Failed to apply performance pragmas: {e}")


def get_db_path():
    """
    Get database path for Widget-Only architecture
    Replacement for documents.knowledge_base.database.get_db_path()
    """
    return Config.DATABASE_PATH


@contextmanager
def get_db_connection():
    """
    Get database connection as context manager
    Replacement for auth.database.get_db_connection()
    """
    conn = None
    try:
        # Ensure database directory exists
        os.makedirs(os.path.dirname(Config.DATABASE_PATH), exist_ok=True)

        # Create connection
        conn = sqlite3.connect(Config.DATABASE_PATH)
        conn.row_factory = sqlite3.Row  # Enable column access by name

        # SQLite Performance Optimizations for Widget Backend
        _apply_performance_pragmas(conn)

        yield conn

    except Exception as e:
        logger.error(f"Database connection error: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            # Run query optimization before closing
            try:
                conn.execute("PRAGMA optimize")
            except Exception as e:
                logger.debug(f"PRAGMA optimize failed: {e}")

            conn.close()


def init_database():
    """
    Initialize database with required tables
    Replacement for auth.database.init_database()
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Create tables for Widget-Only architecture
            cursor.executescript("""
                -- Widget logging table (Widget-Analytics)
                CREATE TABLE IF NOT EXISTS widget_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    question TEXT NOT NULL,
                    response TEXT,
                    response_time_ms INTEGER,
                    llm_provider TEXT,
                    bookstack_page_url TEXT,
                    bookstack_page_title TEXT,
                    timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                -- BookStack content sync (Widget-Kontext)
                CREATE TABLE IF NOT EXISTS bookstack_content (
                    id INTEGER PRIMARY KEY,
                    bookstack_id INTEGER UNIQUE NOT NULL,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT,
                    url TEXT,
                    book_id INTEGER,
                    chapter_id INTEGER,
                    tags TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    synced_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS bookstack_chunks (
                    id INTEGER PRIMARY KEY,
                    bookstack_id INTEGER NOT NULL,
                    content_type TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    chunk_text TEXT NOT NULL,
                    start_pos INTEGER NOT NULL,
                    end_pos INTEGER NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (bookstack_id) REFERENCES bookstack_content (bookstack_id) ON DELETE CASCADE
                );

                -- Create indexes for Widget-Only performance
                CREATE INDEX IF NOT EXISTS idx_widget_logs_session_id ON widget_logs(session_id);
                CREATE INDEX IF NOT EXISTS idx_bookstack_content_id ON bookstack_content(bookstack_id);
                CREATE INDEX IF NOT EXISTS idx_bookstack_chunks_id ON bookstack_chunks(bookstack_id);
            """)

            conn.commit()
            logger.info("Database initialized successfully")

    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise


def get_database_stats():
    """
    Get basic database statistics
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            stats = {}

            # kb_documents table removed in Widget-Only architecture

            # Count widget logs
            cursor.execute("SELECT COUNT(*) FROM widget_logs")
            stats["widget_logs"] = cursor.fetchone()[0]

            # Count bookstack content
            cursor.execute("SELECT COUNT(*) FROM bookstack_content")
            stats["bookstack_content"] = cursor.fetchone()[0]

            return stats

    except Exception as e:
        logger.error(f"Database stats error: {e}")
        return {"widget_logs": 0, "bookstack_content": 0}
