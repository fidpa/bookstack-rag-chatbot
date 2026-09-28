#!/usr/bin/env python3
"""
Startup schema setup.

Creates the BookStack index and the knowledge-base tables on first start and
repairs installations made by older versions (see ensure_bookstack_schema and
ensure_kb_schema). Safe to run on every start.
"""

import logging
import sqlite3
import sys

from bookstack.sync_service import ensure_bookstack_schema
from documents.knowledge_base.schema import ensure_kb_schema
from utils.database import get_db_path

logger = logging.getLogger(__name__)


def run_startup_migrations() -> bool:
    """
    Bring the database schema up to date.

    Returns:
        True on success. A failure is logged and reported, not raised, so the
        app still starts and /health stays reachable.
    """
    db_path = get_db_path()
    try:
        ensure_bookstack_schema(db_path)
        ensure_kb_schema(db_path)
        with sqlite3.connect(db_path) as conn:
            # Refresh the query planner's statistics once per start
            conn.execute("PRAGMA optimize")
            if (
                conn.execute("SELECT COUNT(*) FROM bookstack_content").fetchone()[0]
                == 0
            ):
                logger.warning(
                    "The BookStack index is empty. Populate it with: "
                    "python resync.py --full-resync"
                )
        return True
    except Exception as e:
        logger.error(f"Schema setup failed for {db_path}: {e}")
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.exit(0 if run_startup_migrations() else 1)
