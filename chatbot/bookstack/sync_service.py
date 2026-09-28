"""BookStack content synchronization service.

Mirrors BookStack pages/chapters/books into the local FTS index, with
overlap-aware chunking for retrieval.
"""

import json
import os
import logging
import re
import sqlite3
from contextlib import contextmanager
from html import unescape
from typing import Dict, Iterator, Optional, Set, Tuple

from .chunking import BookStackChunkingService
from utils.database import get_db_path
from utils.timezone_helpers import format_for_database

logger = logging.getLogger(__name__)

# BookStack numbers books, chapters and pages independently, so an id is only
# unique together with its type. The FTS tables use external content, which
# means their triggers must remove old terms with the special 'delete' command:
# a plain DELETE or UPDATE on the FTS table reads the terms to remove from the
# content table, where they are already gone or already replaced.
BOOKSTACK_SCHEMA = """
CREATE TABLE IF NOT EXISTS bookstack_content (
    id INTEGER PRIMARY KEY,
    bookstack_id INTEGER NOT NULL,
    type TEXT NOT NULL, -- 'page', 'chapter', 'book'
    title TEXT NOT NULL,
    content TEXT,
    url TEXT,
    book_id INTEGER,
    chapter_id INTEGER,
    tags TEXT, -- JSON array
    created_at TEXT,
    updated_at TEXT,
    synced_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(bookstack_id, type)
);

CREATE TABLE IF NOT EXISTS bookstack_chunks (
    id INTEGER PRIMARY KEY,
    bookstack_id INTEGER NOT NULL,
    content_type TEXT NOT NULL, -- 'page', 'chapter', 'book'
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    start_pos INTEGER NOT NULL,
    end_pos INTEGER NOT NULL,
    word_count INTEGER NOT NULL,
    title TEXT,
    url TEXT,
    book_id INTEGER,
    chapter_id INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(bookstack_id, content_type, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_bookstack_content_book ON bookstack_content(book_id);
CREATE INDEX IF NOT EXISTS idx_bookstack_content_chapter ON bookstack_content(chapter_id);
CREATE INDEX IF NOT EXISTS idx_bookstack_chunks_book ON bookstack_chunks(book_id);
CREATE INDEX IF NOT EXISTS idx_bookstack_chunks_chapter ON bookstack_chunks(chapter_id);

CREATE VIRTUAL TABLE IF NOT EXISTS bookstack_fts USING fts5(
    title, content, tags,
    content=bookstack_content,
    content_rowid=id
);

CREATE VIRTUAL TABLE IF NOT EXISTS bookstack_chunks_fts USING fts5(
    title, chunk_text, content_type,
    content=bookstack_chunks,
    content_rowid=id
);

CREATE TRIGGER IF NOT EXISTS bookstack_fts_insert
AFTER INSERT ON bookstack_content BEGIN
    INSERT INTO bookstack_fts(rowid, title, content, tags)
    VALUES (new.id, new.title, new.content, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS bookstack_fts_delete
AFTER DELETE ON bookstack_content BEGIN
    INSERT INTO bookstack_fts(bookstack_fts, rowid, title, content, tags)
    VALUES ('delete', old.id, old.title, old.content, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS bookstack_fts_update
AFTER UPDATE ON bookstack_content BEGIN
    INSERT INTO bookstack_fts(bookstack_fts, rowid, title, content, tags)
    VALUES ('delete', old.id, old.title, old.content, old.tags);
    INSERT INTO bookstack_fts(rowid, title, content, tags)
    VALUES (new.id, new.title, new.content, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS bookstack_chunks_fts_insert
AFTER INSERT ON bookstack_chunks BEGIN
    INSERT INTO bookstack_chunks_fts(rowid, title, chunk_text, content_type)
    VALUES (new.id, new.title, new.chunk_text, new.content_type);
END;

CREATE TRIGGER IF NOT EXISTS bookstack_chunks_fts_delete
AFTER DELETE ON bookstack_chunks BEGIN
    INSERT INTO bookstack_chunks_fts(bookstack_chunks_fts, rowid, title, chunk_text, content_type)
    VALUES ('delete', old.id, old.title, old.chunk_text, old.content_type);
END;

CREATE TRIGGER IF NOT EXISTS bookstack_chunks_fts_update
AFTER UPDATE ON bookstack_chunks BEGIN
    INSERT INTO bookstack_chunks_fts(bookstack_chunks_fts, rowid, title, chunk_text, content_type)
    VALUES ('delete', old.id, old.title, old.chunk_text, old.content_type);
    INSERT INTO bookstack_chunks_fts(rowid, title, chunk_text, content_type)
    VALUES (new.id, new.title, new.chunk_text, new.content_type);
END;
"""

# Objects of the pre-0.3 schema, dropped when it is detected. The index is
# derived data; `resync.py --full-resync` rebuilds it from BookStack.
_LEGACY_OBJECTS = [
    ("TRIGGER", "bookstack_fts_insert"),
    ("TRIGGER", "bookstack_fts_update"),
    ("TRIGGER", "bookstack_fts_delete"),
    ("TRIGGER", "bookstack_chunks_fts_insert"),
    ("TRIGGER", "bookstack_chunks_fts_update"),
    ("TRIGGER", "bookstack_chunks_fts_delete"),
    ("TABLE", "bookstack_fts"),
    ("TABLE", "bookstack_chunks_fts"),
    ("TABLE", "bookstack_chunks"),
    ("TABLE", "bookstack_content"),
]

# Block-level tags that end a line of text. Keeping those breaks lets the
# chunker split lists, tables and headings, which carry no sentence punctuation.
_BLOCK_TAGS = re.compile(
    r"<\s*(br|/p|/div|/li|/tr|/h[1-6]|/pre|/blockquote|/table|/ul|/ol)\b[^>]*>",
    re.IGNORECASE,
)
_INVISIBLE = re.compile(r"<(script|style)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)


def _is_legacy_schema(conn: sqlite3.Connection) -> bool:
    """True if bookstack_content exists without the (bookstack_id, type) key."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'bookstack_content'"
    ).fetchone()
    return row is not None and "UNIQUE(bookstack_id,type)" not in re.sub(
        r"\s+", "", row[0]
    )


# Database files whose schema this process has already checked
_schema_checked: Set[str] = set()


def ensure_bookstack_schema(db_path: Optional[str] = None) -> bool:
    """
    Create the BookStack index schema, replacing the pre-0.3 layout if found.

    Returns:
        True if a legacy index was dropped and needs a full resync.
    """
    db_path = db_path or get_db_path()
    if db_path in _schema_checked:
        return False
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(db_path, timeout=30)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        dropped = _is_legacy_schema(conn)
        drops = "".join(
            f"DROP {kind} IF EXISTS {name};\n" for kind, name in _LEGACY_OBJECTS
        )
        conn.executescript(
            "BEGIN IMMEDIATE;\n"
            + (drops if dropped else "")
            + BOOKSTACK_SCHEMA
            + "\nCOMMIT;"
        )
        if dropped:
            logger.warning(
                "Dropped the BookStack index built by an older version (its key "
                "and FTS triggers were wrong). Rebuild it with: "
                "python resync.py --full-resync"
            )
        _schema_checked.add(db_path)
        return dropped
    finally:
        conn.close()


def clean_html_content(html: str) -> str:
    """
    Turn BookStack HTML into plain text, keeping one line per block element.

    Args:
        html: Raw HTML from BookStack

    Returns:
        Text with horizontal whitespace collapsed and blocks on separate lines
    """
    if not html:
        return ""

    text = _INVISIBLE.sub(" ", html)
    text = _BLOCK_TAGS.sub("\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t\r\f\v\xa0]+", " ", text)
    text = re.sub(r" ([.,;:!?])", r"\1", text)  # "<b>apt</b>." left "apt ."
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class ContentSyncService:
    """
    Service for synchronizing BookStack content with local knowledge base
    """

    def __init__(
        self,
        bookstack_client,
        db_path: Optional[str] = None,
        enable_chunking: bool = True,
    ):
        """
        Initialize sync service

        Args:
            bookstack_client: BookStackClient instance
            db_path: Path to SQLite database (default: DATABASE_PATH)
            enable_chunking: Whether to use intelligent chunking (default: True)
        """
        self.client = bookstack_client
        self.db_path = db_path or get_db_path()
        self.enable_chunking = enable_chunking
        self.chunking_service = BookStackChunkingService() if enable_chunking else None
        self.external_url = os.getenv("BOOKSTACK_EXTERNAL_URL", "").rstrip("/")
        # Chapters and pages that failed to load during a sync_all() walk
        self._walk_errors = 0

        ensure_bookstack_schema(self.db_path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """One connection per unit of work: commit on success, always close."""
        conn = sqlite3.connect(self.db_path, timeout=30)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # Kept as a method for callers that used it before it moved to module level.
    def clean_html_content(self, html: str) -> str:
        return clean_html_content(html)

    def _item_url(self, item: Dict, content_type: str) -> str:
        """
        The item's public URL.

        BookStack returns `url` in list and `contents` entries but not in every
        read response. Pages have a permalink by id; books and chapters need slugs.
        """
        if item.get("url"):
            return item["url"]
        if not self.external_url:
            return ""
        if content_type == "page":
            return f"{self.external_url}/link/{item['id']}"
        if content_type == "book" and item.get("slug"):
            return f"{self.external_url}/books/{item['slug']}"
        if content_type == "chapter" and item.get("slug") and item.get("book_slug"):
            return (
                f"{self.external_url}/books/{item['book_slug']}/chapter/{item['slug']}"
            )
        return ""

    def sync_all(self, prune: bool = True) -> Dict[str, int]:
        """
        Walk the whole BookStack API and reindex everything.

        This is the repair path for an index that has drifted, for instance after
        webhooks failed silently for a while.

        Args:
            prune: Also delete index rows for content BookStack no longer reports.
                   Set False to add and update only.

        Returns:
            Statistics dict with counts
        """
        stats = {"books": 0, "chapters": 0, "pages": 0, "removed": 0, "errors": 0}
        seen: Set[Tuple[int, str]] = set()

        # A full walk must see BookStack as it is now, not as cached minutes ago.
        self.client.invalidate_cache()
        self._walk_errors = 0

        books = self.client.get_all_books()
        for book in books:
            if self.sync_book(book["id"], seen=seen):
                stats["books"] += 1
            else:
                stats["errors"] += 1

        stats["chapters"] = sum(1 for _, t in seen if t == "chapter")
        stats["pages"] = sum(1 for _, t in seen if t == "page")
        stats["errors"] += self._walk_errors

        # Prune only after a clean walk: a book, chapter or page that failed to
        # load is missing from `seen`, and pruning would delete it from the index.
        if prune and not stats["errors"] and seen:
            stats["removed"] = self.prune_index(seen)
        elif prune:
            logger.warning(
                "Skipping prune: the sync did not complete cleanly, so the "
                "set of live content is not trustworthy"
            )

        logger.info(f"Sync completed: {stats}")
        return stats

    def sync_book(
        self, book_id: int, seen: Optional[Set[Tuple[int, str]]] = None
    ) -> bool:
        """
        Sync a book with all its chapters and pages.

        Args:
            book_id: BookStack book ID
            seen: Optional set that collects the (id, type) pairs touched

        Returns:
            False if the book itself could not be loaded or stored
        """
        try:
            book = self.client.get_book(book_id)
            if not book:
                logger.warning(f"Book {book_id} could not be loaded")
                return False

            self._store_content(
                bookstack_id=book["id"],
                type="book",
                title=book.get("name", ""),
                content=clean_html_content(
                    book.get("description_html") or book.get("description", "")
                ),
                url=self._item_url(book, "book"),
                tags=book.get("tags", []),
            )
            if seen is not None:
                seen.add((book["id"], "book"))

            # The book read endpoint lists chapters and top-level pages together
            # under `contents`; each chapter entry carries its pages as well.
            for item in book.get("contents", []):
                if item.get("type") == "chapter":
                    ok = self.sync_chapter(item["id"], seen=seen)
                elif item.get("type") == "page":
                    ok = self.sync_page(item["id"], seen=seen, url=item.get("url"))
                else:
                    continue
                if not ok:
                    self._walk_errors += 1
            return True

        except Exception as e:
            logger.error(f"Error syncing book {book_id}: {e}")
            return False

    def sync_chapter(
        self, chapter_id: int, seen: Optional[Set[Tuple[int, str]]] = None
    ) -> bool:
        """
        Sync a chapter and its pages.

        Args:
            chapter_id: BookStack chapter ID
            seen: Optional set that collects the (id, type) pairs touched

        Returns:
            False if the chapter itself could not be loaded or stored
        """
        try:
            chapter = self.client.get_chapter(chapter_id)
            if not chapter:
                logger.warning(f"Chapter {chapter_id} could not be loaded")
                return False

            self._store_content(
                bookstack_id=chapter["id"],
                type="chapter",
                title=chapter.get("name", ""),
                content=clean_html_content(
                    chapter.get("description_html") or chapter.get("description", "")
                ),
                url=self._item_url(chapter, "chapter"),
                book_id=chapter.get("book_id"),
                tags=chapter.get("tags", []),
            )
            if seen is not None:
                seen.add((chapter["id"], "chapter"))

            for page in chapter.get("pages", []):
                if not self.sync_page(page["id"], seen=seen, url=page.get("url")):
                    self._walk_errors += 1
            return True

        except Exception as e:
            logger.error(f"Error syncing chapter {chapter_id}: {e}")
            return False

    def sync_page(
        self,
        page_id: int,
        seen: Optional[Set[Tuple[int, str]]] = None,
        url: Optional[str] = None,
    ) -> bool:
        """
        Sync a single page.

        Args:
            page_id: BookStack page ID
            seen: Optional set that collects the (id, type) pairs touched
            url: The page URL if the caller already knows it (webhook payload,
                 book contents); otherwise derived from BOOKSTACK_EXTERNAL_URL

        Returns:
            False if the page could not be loaded or stored
        """
        try:
            page = self.client.get_page(page_id)
            if not page:
                logger.warning(f"Page {page_id} could not be loaded")
                return False

            # Drafts are private to their author and not part of the wiki yet
            if page.get("draft"):
                return True

            self._store_content(
                bookstack_id=page["id"],
                type="page",
                title=page.get("name", ""),
                content=clean_html_content(page.get("html", "")),
                url=url or self._item_url(page, "page"),
                book_id=page.get("book_id"),
                chapter_id=page.get("chapter_id") or None,
                tags=page.get("tags", []),
            )
            if seen is not None:
                seen.add((page["id"], "page"))
            return True

        except Exception as e:
            logger.error(f"Error syncing page {page_id}: {e}")
            return False

    def _store_content(
        self,
        bookstack_id: int,
        type: str,
        title: str,
        content: str,
        url: str = "",
        book_id: Optional[int] = None,
        chapter_id: Optional[int] = None,
        tags: Optional[list] = None,
    ):
        """
        Upsert one item and replace its chunks, in a single transaction.

        Args:
            bookstack_id: ID from BookStack
            type: Content type (book, chapter, page)
            title: Content title
            content: Cleaned text content
            url: BookStack URL
            book_id: Parent book ID
            chapter_id: Parent chapter ID
            tags: List of tags
        """
        chunks = []
        if self.chunking_service and content:
            chunks = self.chunking_service.chunk_bookstack_content(
                text=content,
                bookstack_id=bookstack_id,
                content_type=type,
                title=title,
                url=url,
                book_id=book_id,
                chapter_id=chapter_id,
            )

        with self._connect() as conn:
            # ON CONFLICT ... DO UPDATE fires the UPDATE trigger, which keeps the
            # FTS index consistent. INSERT OR REPLACE would delete the row without
            # firing the DELETE trigger and leave stale terms behind.
            conn.execute(
                """
                INSERT INTO bookstack_content
                (bookstack_id, type, title, content, url, book_id, chapter_id, tags, synced_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(bookstack_id, type) DO UPDATE SET
                    title = excluded.title,
                    content = excluded.content,
                    url = excluded.url,
                    book_id = excluded.book_id,
                    chapter_id = excluded.chapter_id,
                    tags = excluded.tags,
                    synced_at = excluded.synced_at
                """,
                (
                    bookstack_id,
                    type,
                    title,
                    content,
                    url,
                    book_id,
                    chapter_id,
                    json.dumps(tags or []),
                    format_for_database(),
                ),
            )

            if self.chunking_service:
                conn.execute(
                    "DELETE FROM bookstack_chunks WHERE bookstack_id = ? AND content_type = ?",
                    (bookstack_id, type),
                )
                conn.executemany(
                    """
                    INSERT INTO bookstack_chunks
                    (bookstack_id, content_type, chunk_index, chunk_text, start_pos, end_pos,
                     word_count, title, url, book_id, chapter_id)
                    VALUES (:bookstack_id, :content_type, :chunk_index, :chunk_text,
                            :start_pos, :end_pos, :word_count, :title, :url, :book_id,
                            :chapter_id)
                    """,
                    [chunk.to_dict() for chunk in chunks],
                )

        logger.debug(f"Stored {type} {bookstack_id} ({len(chunks)} chunks): {title}")

    def remove_page_from_index(self, page_id: int):
        """
        Remove a page from the index (both content and chunks)

        Args:
            page_id: BookStack page ID
        """
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM bookstack_content WHERE bookstack_id = ? AND type = ?",
                (page_id, "page"),
            )
            conn.execute(
                "DELETE FROM bookstack_chunks WHERE bookstack_id = ? AND content_type = ?",
                (page_id, "page"),
            )
        logger.info(f"Removed page {page_id} from index (content and chunks)")

    def remove_chapter_from_index(self, chapter_id: int) -> int:
        """
        Remove a chapter and every page inside it from the index.

        The BookStack API cannot help here: by the time the chapter_delete webhook
        arrives, the chapter is gone and get_chapter() returns nothing. The pages are
        found through the chapter_id column that sync_page() records instead.

        Args:
            chapter_id: BookStack chapter ID

        Returns:
            Number of content rows removed
        """
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM bookstack_chunks WHERE chapter_id = ?", (chapter_id,)
            )
            conn.execute(
                "DELETE FROM bookstack_chunks WHERE bookstack_id = ? AND content_type = ?",
                (chapter_id, "chapter"),
            )
            removed = conn.execute(
                "DELETE FROM bookstack_content WHERE chapter_id = ?", (chapter_id,)
            ).rowcount
            removed += conn.execute(
                "DELETE FROM bookstack_content WHERE bookstack_id = ? AND type = ?",
                (chapter_id, "chapter"),
            ).rowcount

        logger.info(
            f"Removed chapter {chapter_id} and its pages from index "
            f"({removed} content rows)"
        )
        return removed

    def remove_book_from_index(self, book_id: int) -> int:
        """
        Remove a book, its chapters and all its pages from the index.

        Args:
            book_id: BookStack book ID

        Returns:
            Number of content rows removed
        """
        with self._connect() as conn:
            conn.execute("DELETE FROM bookstack_chunks WHERE book_id = ?", (book_id,))
            conn.execute(
                "DELETE FROM bookstack_chunks WHERE bookstack_id = ? AND content_type = ?",
                (book_id, "book"),
            )
            removed = conn.execute(
                "DELETE FROM bookstack_content WHERE book_id = ?", (book_id,)
            ).rowcount
            removed += conn.execute(
                "DELETE FROM bookstack_content WHERE bookstack_id = ? AND type = ?",
                (book_id, "book"),
            ).rowcount

        logger.info(
            f"Removed book {book_id} and its contents from index "
            f"({removed} content rows)"
        )
        return removed

    def prune_index(self, keep: Set[Tuple[int, str]]) -> int:
        """
        Delete index rows for content BookStack no longer reports.

        Args:
            keep: (bookstack_id, type) pairs seen during a full sync

        Returns:
            Number of content rows removed
        """
        with self._connect() as conn:
            stale = [
                (bookstack_id, content_type)
                for bookstack_id, content_type in conn.execute(
                    "SELECT bookstack_id, type FROM bookstack_content"
                )
                if (bookstack_id, content_type) not in keep
            ]

            for bookstack_id, content_type in stale:
                conn.execute(
                    "DELETE FROM bookstack_chunks "
                    "WHERE bookstack_id = ? AND content_type = ?",
                    (bookstack_id, content_type),
                )
                conn.execute(
                    "DELETE FROM bookstack_content WHERE bookstack_id = ? AND type = ?",
                    (bookstack_id, content_type),
                )

        if stale:
            logger.info(f"Pruned {len(stale)} stale rows from the index")
        return len(stale)

    def get_sync_stats(self) -> Dict:
        """
        Get synchronization statistics including chunk data

        Returns:
            Dict with content counts, chunk stats and last sync time
        """
        with self._connect() as conn:
            counts = dict(
                conn.execute(
                    "SELECT type, COUNT(*) FROM bookstack_content GROUP BY type"
                ).fetchall()
            )
            chunk_counts = dict(
                conn.execute(
                    "SELECT content_type, COUNT(*) FROM bookstack_chunks "
                    "GROUP BY content_type"
                ).fetchall()
            )
            last_sync = conn.execute(
                "SELECT MAX(synced_at) FROM bookstack_content"
            ).fetchone()[0]

            chunking_stats = {}
            if chunk_counts:
                total, avg, low, high, words = conn.execute("""
                    SELECT COUNT(*), AVG(word_count), MIN(word_count),
                           MAX(word_count), SUM(word_count)
                    FROM bookstack_chunks
                """).fetchone()
                chunking_stats = {
                    "total_chunks": total,
                    "avg_words_per_chunk": round(avg or 0, 1),
                    "min_words": low or 0,
                    "max_words": high or 0,
                    "total_words": words or 0,
                    "chunks_by_type": chunk_counts,
                }

        return {
            "content_counts": counts,
            "chunk_stats": chunking_stats,
            "last_sync": last_sync,
            "total_content": sum(counts.values()),
            "chunking_enabled": self.enable_chunking,
        }
