#!/usr/bin/env python3
"""
Startup Migrations
Automatically runs pending database migrations when the application starts
"""

import os
import sys
import sqlite3
import logging
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_db_path():
    """Get the database path (honours DATABASE_PATH env var)."""
    return os.environ.get('DATABASE_PATH') or os.path.join(
        os.path.dirname(__file__), 'data', 'chatbot.db'
    )


def check_and_run_migrations():
    """Check for and run any pending migrations"""
    try:
        db_path = get_db_path()

        # Ensure data directory exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()

            # Create migrations table if it doesn't exist
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS db_migrations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    migration_name TEXT UNIQUE NOT NULL,
                    description TEXT,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Check for widget logging migration
            cursor.execute("""
                SELECT migration_name FROM db_migrations
                WHERE migration_name = 'add_widget_logging'
            """)

            if not cursor.fetchone():
                logger.info("Running widget logging migration...")
                run_widget_logging_migration(cursor)
                conn.commit()
                logger.info("Widget logging migration completed")
            else:
                logger.debug("Widget logging migration already applied")

    except Exception as e:
        logger.error(f"Migration check failed: {str(e)}")
        # Don't fail the app startup, just log the error
        return False

    return True


def run_widget_logging_migration(cursor):
    """Run the widget logging migration"""

    # Check if widget_chat_logs table already exists
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='widget_chat_logs'
    """)

    if cursor.fetchone():
        logger.info("Widget logging tables already exist")
        # Just record the migration as applied
        cursor.execute("""
            INSERT OR IGNORE INTO db_migrations (migration_name, description)
            VALUES (?, ?)
        """, ('add_widget_logging', 'Add Widget Chat Logging tables and indices'))
        return

    # Read and execute migration SQL
    migration_file = os.path.join(
        os.path.dirname(__file__),
        'auth/database/migrations/add_widget_logging.sql'
    )

    if not os.path.exists(migration_file):
        logger.error(f"Migration file not found: {migration_file}")
        return

    with open(migration_file, 'r', encoding='utf-8') as f:
        migration_sql = f.read()

    # Execute migration
    cursor.executescript(migration_sql)

    # Record migration
    cursor.execute("""
        INSERT INTO db_migrations (migration_name, description)
        VALUES (?, ?)
    """, ('add_widget_logging', 'Add Widget Chat Logging tables and indices'))


def verify_migrations():
    """Verify that all expected tables exist"""
    try:
        db_path = get_db_path()

        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()

            # Check for required tables
            required_tables = [
                'widget_chat_logs',
                'widget_chat_fts'
            ]

            missing_tables = []
            for table in required_tables:
                cursor.execute("""
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name=?
                """, (table,))

                if not cursor.fetchone():
                    missing_tables.append(table)

            if missing_tables:
                logger.warning(f"Missing tables after migration: {missing_tables}")
                return False
            else:
                logger.debug("All required tables exist")
                return True

    except Exception as e:
        logger.error(f"Migration verification failed: {str(e)}")
        return False


if __name__ == "__main__":
    print("🔄 Running startup migrations...")

    success = check_and_run_migrations()
    if success:
        verification_success = verify_migrations()
        if verification_success:
            print("✅ All migrations completed successfully")
        else:
            print("⚠️ Migration verification failed")
            sys.exit(1)
    else:
        print("❌ Migration failed")
        sys.exit(1)