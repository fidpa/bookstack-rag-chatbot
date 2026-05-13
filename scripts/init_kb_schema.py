#!/usr/bin/env python3
"""
Initialize Knowledge Base Schema
Creates all required KB tables (kb_documents, kb_chunks, kb_chunks_fts, kb_tags)
Based on RAG_ADMIN_GUIDE.md specification
"""

import os
import sys
import sqlite3
import logging
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def get_db_path():
    """Get database path"""
    # Check if running in container
    if os.path.exists('/app/data'):
        db_path = '/app/data/chatbot.db'
    elif os.path.exists('/data'):
        db_path = '/data/chatbot.db'
    else:
        db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'chatbot.db')

    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    return db_path


def check_existing_tables(cursor):
    """Check which KB tables already exist"""
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name LIKE 'kb_%'
        ORDER BY name
    """)
    existing = [row[0] for row in cursor.fetchall()]
    return existing


def init_kb_schema(force=False):
    """Initialize KB database schema"""
    db_path = get_db_path()
    logger.info(f"📂 Database: {db_path}")

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check existing tables
        existing_tables = check_existing_tables(cursor)

        if existing_tables:
            logger.warning(f"⚠️  Existing KB tables: {', '.join(existing_tables)}")
            if not force:
                response = input("Tables exist. Drop and recreate? (yes/no): ")
                if response.lower() != 'yes':
                    logger.info("❌ Aborted. Use --force to skip confirmation.")
                    return False

            # Drop existing KB tables
            logger.info("🗑️  Dropping existing KB tables...")
            for table in existing_tables:
                cursor.execute(f"DROP TABLE IF EXISTS {table}")
                logger.info(f"   Dropped: {table}")

        # Create kb_documents table
        logger.info("📄 Creating kb_documents table...")
        cursor.execute("""
            CREATE TABLE kb_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                file_type TEXT NOT NULL,
                title TEXT,
                description TEXT,
                content_hash TEXT UNIQUE NOT NULL,
                uploaded_by TEXT DEFAULT 'system',
                uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_indexed TEXT,
                is_active BOOLEAN DEFAULT 1,
                chunking_status TEXT DEFAULT 'pending',
                chunk_count INTEGER DEFAULT 0
            )
        """)

        # Create kb_chunks table
        logger.info("📦 Creating kb_chunks table...")
        cursor.execute("""
            CREATE TABLE kb_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                chunk_text TEXT NOT NULL,
                start_pos INTEGER NOT NULL DEFAULT 0,
                end_pos INTEGER NOT NULL DEFAULT 0,
                word_count INTEGER NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(doc_id, chunk_index),
                FOREIGN KEY (doc_id) REFERENCES kb_documents (id) ON DELETE CASCADE
            )
        """)

        # Create FTS5 index for chunks
        logger.info("🔍 Creating kb_chunks_fts virtual table...")
        cursor.execute("""
            CREATE VIRTUAL TABLE kb_chunks_fts
            USING fts5(
                chunk_text,
                content='kb_chunks',
                content_rowid='id'
            )
        """)

        # Create kb_tags table
        logger.info("🏷️  Creating kb_tags table...")
        cursor.execute("""
            CREATE TABLE kb_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                tag TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (document_id) REFERENCES kb_documents (id) ON DELETE CASCADE
            )
        """)

        # Create indexes for performance
        logger.info("⚡ Creating indexes...")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_kb_chunks_doc_id ON kb_chunks(doc_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_kb_tags_document_id ON kb_tags(document_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_kb_tags_tag ON kb_tags(tag)")

        # Create FTS triggers for automatic sync
        logger.info("🔄 Creating FTS triggers...")
        cursor.executescript("""
            -- Trigger: Insert into FTS when chunk is added
            CREATE TRIGGER kb_chunks_ai AFTER INSERT ON kb_chunks BEGIN
                INSERT INTO kb_chunks_fts(rowid, chunk_text)
                VALUES (new.id, new.chunk_text);
            END;

            -- Trigger: Update FTS when chunk is updated
            CREATE TRIGGER kb_chunks_au AFTER UPDATE ON kb_chunks BEGIN
                UPDATE kb_chunks_fts SET chunk_text = new.chunk_text
                WHERE rowid = new.id;
            END;

            -- Trigger: Delete from FTS when chunk is deleted
            CREATE TRIGGER kb_chunks_ad AFTER DELETE ON kb_chunks BEGIN
                DELETE FROM kb_chunks_fts WHERE rowid = old.id;
            END;
        """)

        conn.commit()

        # Verify creation
        tables = check_existing_tables(cursor)
        logger.info(f"\n✅ Successfully created {len(tables)} KB tables:")
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            logger.info(f"   - {table} ({count} rows)")

        conn.close()
        return True

    except Exception as e:
        logger.error(f"❌ Schema initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Initialize Knowledge Base Schema')
    parser.add_argument('--force', action='store_true', help='Skip confirmation prompts')
    args = parser.parse_args()

    print("=" * 60)
    print("🚀 Knowledge Base Schema Initialization")
    print("=" * 60)
    print()

    success = init_kb_schema(force=args.force)

    if success:
        print("\n" + "=" * 60)
        print("✅ Schema initialization complete!")
        print("=" * 60)
        print("\n📝 Next steps:")
        print("   1. Upload documents: docker exec chatbot python3 /app/scripts/upload_pdf_to_kb.py <file>")
        print("   2. Check status: docker exec chatbot python3 /app/scripts/kb_admin.py stats overview")
        sys.exit(0)
    else:
        print("\n❌ Schema initialization failed")
        sys.exit(1)
