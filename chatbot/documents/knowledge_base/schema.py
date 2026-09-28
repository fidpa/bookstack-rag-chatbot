"""Schema of the uploaded-documents knowledge base (kb_* tables)."""

import logging
import os
import sqlite3
from typing import Optional

from utils.database import get_db_path

logger = logging.getLogger(__name__)

# kb_chunks_fts uses external content, so its triggers remove old terms with the
# special 'delete' command. A plain DELETE or UPDATE on the FTS table reads the
# terms to remove from kb_chunks, where they are already gone or replaced.
KB_SCHEMA = """
CREATE TABLE IF NOT EXISTS kb_documents (
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
);

CREATE TABLE IF NOT EXISTS kb_chunks (
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
);

CREATE TABLE IF NOT EXISTS kb_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    tag TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (document_id) REFERENCES kb_documents (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_kb_chunks_doc_id ON kb_chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_kb_tags_document_id ON kb_tags(document_id);
CREATE INDEX IF NOT EXISTS idx_kb_tags_tag ON kb_tags(tag);

CREATE VIRTUAL TABLE IF NOT EXISTS kb_chunks_fts USING fts5(
    chunk_text,
    content='kb_chunks',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS kb_chunks_ai AFTER INSERT ON kb_chunks BEGIN
    INSERT INTO kb_chunks_fts(rowid, chunk_text) VALUES (new.id, new.chunk_text);
END;

CREATE TRIGGER IF NOT EXISTS kb_chunks_ad AFTER DELETE ON kb_chunks BEGIN
    INSERT INTO kb_chunks_fts(kb_chunks_fts, rowid, chunk_text)
    VALUES ('delete', old.id, old.chunk_text);
END;

CREATE TRIGGER IF NOT EXISTS kb_chunks_au AFTER UPDATE ON kb_chunks BEGIN
    INSERT INTO kb_chunks_fts(kb_chunks_fts, rowid, chunk_text)
    VALUES ('delete', old.id, old.chunk_text);
    INSERT INTO kb_chunks_fts(rowid, chunk_text) VALUES (new.id, new.chunk_text);
END;
"""

KB_TABLES = ["kb_chunks_fts", "kb_tags", "kb_chunks", "kb_documents"]


def _has_legacy_triggers(conn: sqlite3.Connection) -> bool:
    """True if kb_chunks carries the pre-0.3 triggers that corrupt the FTS index."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = 'kb_chunks_ad'"
    ).fetchone()
    return row is not None and "'delete'" not in row[0]


def ensure_kb_schema(db_path: Optional[str] = None, drop: bool = False) -> bool:
    """
    Create the knowledge-base tables, and repair an index built by older versions.

    Unlike the BookStack index, the kb_* tables hold the only record of what
    was uploaded, so an old install keeps its rows: the triggers are replaced
    and the FTS index is rebuilt from kb_chunks.

    Args:
        db_path: SQLite file (default: DATABASE_PATH)
        drop: Drop all kb_* tables first (kb_admin/init_kb_schema --force)

    Returns:
        True if an existing FTS index was rebuilt.
    """
    db_path = db_path or get_db_path()
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(db_path, timeout=30)
    try:
        repair = not drop and _has_legacy_triggers(conn)
        script = ["BEGIN IMMEDIATE;"]
        if drop:
            script += [f"DROP TABLE IF EXISTS {t};" for t in KB_TABLES]
        if repair:
            script += [
                f"DROP TRIGGER IF EXISTS {t};"
                for t in ("kb_chunks_ai", "kb_chunks_ad", "kb_chunks_au")
            ]
        script.append(KB_SCHEMA)
        if repair:
            script.append("INSERT INTO kb_chunks_fts(kb_chunks_fts) VALUES('rebuild');")
        script.append("COMMIT;")
        conn.executescript("\n".join(script))
        if repair:
            logger.warning("Replaced the kb_chunks FTS triggers and rebuilt the index")
        return repair
    finally:
        conn.close()
