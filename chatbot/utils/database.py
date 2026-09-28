"""SQLite connection helpers shared by the app, resync.py and the admin scripts."""

import logging
import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "chatbot.db"
)

# Per-connection settings. journal_mode=WAL is persistent in the file and is set
# once at startup (see startup_migrations.py), not on every connection.
_PRAGMAS = (
    "PRAGMA synchronous = NORMAL",
    "PRAGMA temp_store = MEMORY",
    "PRAGMA cache_size = -8000",  # 8 MB
)


def get_db_path() -> str:
    """DATABASE_PATH, or chatbot/data/chatbot.db next to the code.

    Read on every call, so scripts and tests that set the variable after
    import still reach the right file.
    """
    return os.environ.get("DATABASE_PATH") or _DEFAULT_DB_PATH


@contextmanager
def get_db_connection() -> Iterator[sqlite3.Connection]:
    """
    Connection with sqlite3.Row rows, closed on exit.

    Callers commit their own writes; an exception rolls back.
    """
    conn = sqlite3.connect(get_db_path(), timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        for pragma in _PRAGMAS:
            conn.execute(pragma)
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
