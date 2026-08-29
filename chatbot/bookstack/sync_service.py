"""BookStack content synchronization service.

Mirrors BookStack pages/chapters/books into the local FTS index, with
overlap-aware chunking for retrieval.
"""

import os
import logging
import sqlite3
from typing import List, Dict, Optional, Set, Tuple
from html import unescape
import re

# Import the new chunking service
from .chunking import BookStackChunkingService
from utils.timezone_helpers import format_for_database

logger = logging.getLogger(__name__)


class ContentSyncService:
    """
    Service for synchronizing BookStack content with local knowledge base
    """

    def __init__(
        self, bookstack_client, db_path: str = None, enable_chunking: bool = True
    ):
        """
        Initialize sync service

        Args:
            bookstack_client: BookStackClient instance
            db_path: Path to SQLite database
            enable_chunking: Whether to use intelligent chunking (default: True)
        """
        self.client = bookstack_client
        self.db_path = db_path or os.getenv("DATABASE_PATH", "data/chatbot.db")
        self.enable_chunking = enable_chunking

        # Initialize chunking service if enabled
        if self.enable_chunking:
            self.chunking_service = BookStackChunkingService()
            logger.info("BookStack sync with intelligent chunking enabled")
        else:
            self.chunking_service = None
            logger.info("BookStack sync with simple content storage")

        self._init_db()

    def _init_db(self):
        """Initialize database tables if not exists"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Enable WAL mode for better concurrency and performance
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")

            # BookStack content table (original - kept for compatibility)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bookstack_content (
                    id INTEGER PRIMARY KEY,
                    bookstack_id INTEGER UNIQUE NOT NULL,
                    type TEXT NOT NULL, -- 'page', 'chapter', 'book'
                    title TEXT NOT NULL,
                    content TEXT,
                    url TEXT,
                    book_id INTEGER,
                    chapter_id INTEGER,
                    tags TEXT, -- JSON array
                    created_at TEXT,
                    updated_at TEXT,
                    synced_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # NEW: BookStack chunks table for enhanced RAG
            cursor.execute("""
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
                )
            """)

            # FTS5 table for search (original content)
            cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS bookstack_fts
                USING fts5(
                    title, content, tags,
                    content=bookstack_content,
                    content_rowid=id
                )
            """)

            # NEW: FTS5 table for chunk-based search
            cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS bookstack_chunks_fts
                USING fts5(
                    title, chunk_text, content_type,
                    content=bookstack_chunks,
                    content_rowid=id
                )
            """)

            # Triggers to keep FTS tables in sync

            # Original content FTS triggers
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS bookstack_fts_insert
                AFTER INSERT ON bookstack_content BEGIN
                    INSERT INTO bookstack_fts(rowid, title, content, tags)
                    VALUES (new.id, new.title, new.content, new.tags);
                END
            """)

            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS bookstack_fts_update
                AFTER UPDATE ON bookstack_content BEGIN
                    UPDATE bookstack_fts
                    SET title = new.title, content = new.content, tags = new.tags
                    WHERE rowid = new.id;
                END
            """)

            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS bookstack_fts_delete
                AFTER DELETE ON bookstack_content BEGIN
                    DELETE FROM bookstack_fts WHERE rowid = old.id;
                END
            """)

            # NEW: Chunk FTS triggers
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS bookstack_chunks_fts_insert
                AFTER INSERT ON bookstack_chunks BEGIN
                    INSERT INTO bookstack_chunks_fts(rowid, title, chunk_text, content_type)
                    VALUES (new.id, new.title, new.chunk_text, new.content_type);
                END
            """)

            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS bookstack_chunks_fts_update
                AFTER UPDATE ON bookstack_chunks BEGIN
                    UPDATE bookstack_chunks_fts
                    SET title = new.title, chunk_text = new.chunk_text, content_type = new.content_type
                    WHERE rowid = new.id;
                END
            """)

            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS bookstack_chunks_fts_delete
                AFTER DELETE ON bookstack_chunks BEGIN
                    DELETE FROM bookstack_chunks_fts WHERE rowid = old.id;
                END
            """)

            conn.commit()

    def clean_html_content(self, html: str) -> str:
        """
        Clean HTML content for indexing

        Args:
            html: Raw HTML from BookStack

        Returns:
            Cleaned text content
        """
        if not html:
            return ""

        # Remove HTML tags
        text = re.sub(r"<[^>]+>", " ", html)

        # Unescape HTML entities
        text = unescape(text)

        # Clean up whitespace
        text = re.sub(r"\s+", " ", text)

        return text.strip()

    def sync_all(self, prune: bool = True) -> Dict[str, int]:
        """
        Walk the whole BookStack API and reindex everything.

        This is the repair path for an index that has drifted, for instance after
        webhooks failed silently for a while, or after a chapter was deleted before
        v0.1.5 taught the endpoint to remove its pages.

        Args:
            prune: Also delete index rows for content BookStack no longer reports.
                   Set False to add and update only.

        Returns:
            Statistics dict with counts
        """
        stats = {"books": 0, "chapters": 0, "pages": 0, "removed": 0, "errors": 0}
        seen: Set[Tuple[int, str]] = set()

        try:
            books = self.client.get_all_books()

            for book in books:
                try:
                    self.sync_book(book["id"], seen=seen)
                    stats["books"] += 1
                except Exception as e:
                    logger.error(f"Error syncing book {book['id']}: {e}")
                    stats["errors"] += 1

            stats["chapters"] = sum(1 for _, t in seen if t == "chapter")
            stats["pages"] = sum(1 for _, t in seen if t == "page")

            # Prune only after a clean walk: if fetching books failed, `seen` is
            # empty or partial and pruning would empty the index instead of fixing it.
            if prune and not stats["errors"] and seen:
                stats["removed"] = self.prune_index(seen)
            elif prune:
                logger.warning(
                    "Skipping prune: the sync did not complete cleanly, so the "
                    "set of live content is not trustworthy"
                )

            logger.info(f"Sync completed: {stats}")
            return stats

        except Exception as e:
            logger.error(f"Error during sync: {e}")
            stats["errors"] += 1
            return stats

    def sync_book(self, book_id: int, seen: Optional[Set[Tuple[int, str]]] = None):
        """
        Sync a specific book and all its content

        Args:
            book_id: BookStack book ID
            seen: Optional set that collects the (id, type) pairs touched
        """
        try:
            book = self.client.get_book(book_id)
            if not book:
                logger.warning(f"Book {book_id} not found")
                return

            # Store book metadata
            self._store_content(
                bookstack_id=book["id"],
                type="book",
                title=book.get("name", ""),
                content=self.clean_html_content(book.get("description_html", "")),
                url=book.get("url", ""),
                tags=book.get("tags", []),
            )

            if seen is not None:
                seen.add((book["id"], "book"))

            # Sync chapters
            for chapter in book.get("chapters", []):
                self.sync_chapter(chapter["id"], seen=seen)

            # Sync direct pages
            for page in book.get("pages", []):
                self.sync_page(page["id"], seen=seen)

        except Exception as e:
            logger.error(f"Error syncing book {book_id}: {e}")

    def sync_chapter(
        self, chapter_id: int, seen: Optional[Set[Tuple[int, str]]] = None
    ):
        """
        Sync a specific chapter and its pages

        Args:
            chapter_id: BookStack chapter ID
            seen: Optional set that collects the (id, type) pairs touched
        """
        try:
            chapter = self.client.get_chapter(chapter_id)
            if not chapter:
                logger.warning(f"Chapter {chapter_id} not found")
                return

            # Store chapter metadata
            self._store_content(
                bookstack_id=chapter["id"],
                type="chapter",
                title=chapter.get("name", ""),
                content=self.clean_html_content(chapter.get("description_html", "")),
                url=chapter.get("url", ""),
                book_id=chapter.get("book_id"),
                tags=chapter.get("tags", []),
            )

            if seen is not None:
                seen.add((chapter["id"], "chapter"))

            # Sync pages in chapter
            for page in chapter.get("pages", []):
                self.sync_page(page["id"], seen=seen)

        except Exception as e:
            logger.error(f"Error syncing chapter {chapter_id}: {e}")

    def sync_page(self, page_id: int, seen: Optional[Set[Tuple[int, str]]] = None):
        """
        Sync a specific page

        Args:
            page_id: BookStack page ID
            seen: Optional set that collects the (id, type) pairs touched
        """
        try:
            page = self.client.get_page(page_id)
            if not page:
                logger.warning(f"Page {page_id} not found")
                return

            # Store page content
            self._store_content(
                bookstack_id=page["id"],
                type="page",
                title=page.get("name", ""),
                content=self.clean_html_content(page.get("html", "")),
                url=page.get("url", ""),
                book_id=page.get("book_id"),
                chapter_id=page.get("chapter_id"),
                tags=page.get("tags", []),
            )

            if seen is not None:
                seen.add((page["id"], "page"))

        except Exception as e:
            logger.error(f"Error syncing page {page_id}: {e}")

    def _store_content(
        self,
        bookstack_id: int,
        type: str,
        title: str,
        content: str,
        url: str = "",
        book_id: int = None,
        chapter_id: int = None,
        tags: List = None,
    ):
        """
        Store or update content in database with optional chunking

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
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Convert tags to JSON string
            import json

            tags_json = json.dumps(tags or [])

            # Store original content (mit lokaler Zeitzone)
            sync_time = format_for_database()
            cursor.execute(
                """
                INSERT OR REPLACE INTO bookstack_content
                (bookstack_id, type, title, content, url, book_id, chapter_id, tags, synced_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    bookstack_id,
                    type,
                    title,
                    content,
                    url,
                    book_id,
                    chapter_id,
                    tags_json,
                    sync_time,
                ),
            )

            # Store chunks if chunking is enabled and content is substantial
            # The chunking service will handle empty content check internally
            if self.enable_chunking and self.chunking_service and content:
                self._store_content_chunks(
                    bookstack_id, type, title, content, url, book_id, chapter_id
                )

            conn.commit()
            logger.debug(f"Stored {type} {bookstack_id}: {title}")

    def _store_content_chunks(
        self,
        bookstack_id: int,
        content_type: str,
        title: str,
        content: str,
        url: str,
        book_id: int = None,
        chapter_id: int = None,
    ):
        """
        Store content chunks for enhanced RAG retrieval

        Args:
            bookstack_id: ID from BookStack
            content_type: Content type (book, chapter, page)
            title: Content title
            content: Cleaned text content
            url: BookStack URL
            book_id: Parent book ID
            chapter_id: Parent chapter ID
        """
        try:
            # Generate chunks using the chunking service
            chunks = self.chunking_service.chunk_bookstack_content(
                text=content,
                bookstack_id=bookstack_id,
                content_type=content_type,
                title=title,
                url=url,
                book_id=book_id,
                chapter_id=chapter_id,
            )

            if not chunks:
                logger.warning(f"No chunks generated for {content_type} {bookstack_id}")
                return

            # Remove existing chunks for this content
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM bookstack_chunks WHERE bookstack_id = ? AND content_type = ?",
                    (bookstack_id, content_type),
                )

                # Prepare chunk data for batch insert
                chunk_records = []
                for chunk in chunks:
                    chunk_data = chunk.to_dict()
                    chunk_records.append(
                        (
                            chunk_data["bookstack_id"],
                            chunk_data["content_type"],
                            chunk_data["chunk_index"],
                            chunk_data["chunk_text"],
                            chunk_data["start_pos"],
                            chunk_data["end_pos"],
                            chunk_data["word_count"],
                            chunk_data["title"],
                            chunk_data["url"],
                            chunk_data["book_id"],
                            chunk_data["chapter_id"],
                        )
                    )

                # Batch insert all chunks at once (much faster)
                cursor.executemany(
                    """
                    INSERT INTO bookstack_chunks
                    (bookstack_id, content_type, chunk_index, chunk_text, start_pos, end_pos,
                     word_count, title, url, book_id, chapter_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    chunk_records,
                )

                conn.commit()

            # Log chunking statistics
            stats = self.chunking_service.get_chunk_statistics(chunks)
            logger.info(
                f"Chunked {content_type} {bookstack_id}: {stats['total_chunks']} chunks, "
                f"avg {stats['avg_words_per_chunk']:.0f} words/chunk"
            )

        except Exception as e:
            logger.error(f"Error chunking {content_type} {bookstack_id}: {e}")
            # Continue without chunking - fallback to original content storage

    def remove_page_from_index(self, page_id: int):
        """
        Remove a page from the index (both content and chunks)

        Args:
            page_id: BookStack page ID
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Remove from original content table
            cursor.execute(
                "DELETE FROM bookstack_content WHERE bookstack_id = ? AND type = ?",
                (page_id, "page"),
            )

            # Remove from chunks table
            cursor.execute(
                "DELETE FROM bookstack_chunks WHERE bookstack_id = ? AND content_type = ?",
                (page_id, "page"),
            )

            conn.commit()
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
            Number of content rows removed (chunks follow via the delete triggers)
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute(
                "DELETE FROM bookstack_chunks WHERE chapter_id = ?", (chapter_id,)
            )
            cursor.execute(
                "DELETE FROM bookstack_chunks WHERE bookstack_id = ? AND content_type = ?",
                (chapter_id, "chapter"),
            )
            cursor.execute(
                "DELETE FROM bookstack_content WHERE chapter_id = ?", (chapter_id,)
            )
            removed = cursor.rowcount
            cursor.execute(
                "DELETE FROM bookstack_content WHERE bookstack_id = ? AND type = ?",
                (chapter_id, "chapter"),
            )
            removed += cursor.rowcount

            conn.commit()
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
            Number of content rows removed (chunks follow via the delete triggers)
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("DELETE FROM bookstack_chunks WHERE book_id = ?", (book_id,))
            cursor.execute(
                "DELETE FROM bookstack_chunks WHERE bookstack_id = ? AND content_type = ?",
                (book_id, "book"),
            )
            cursor.execute(
                "DELETE FROM bookstack_content WHERE book_id = ?", (book_id,)
            )
            removed = cursor.rowcount
            cursor.execute(
                "DELETE FROM bookstack_content WHERE bookstack_id = ? AND type = ?",
                (book_id, "book"),
            )
            removed += cursor.rowcount

            conn.commit()
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
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("SELECT bookstack_id, type FROM bookstack_content")
            stale = [
                (row["bookstack_id"], row["type"])
                for row in cursor.fetchall()
                if (row["bookstack_id"], row["type"]) not in keep
            ]

            for bookstack_id, content_type in stale:
                cursor.execute(
                    "DELETE FROM bookstack_chunks "
                    "WHERE bookstack_id = ? AND content_type = ?",
                    (bookstack_id, content_type),
                )
                cursor.execute(
                    "DELETE FROM bookstack_content WHERE bookstack_id = ? AND type = ?",
                    (bookstack_id, content_type),
                )

            conn.commit()
            if stale:
                logger.info(f"Pruned {len(stale)} stale rows from the index")
            return len(stale)

    def search(
        self, query: str, limit: int = 10, use_chunks: bool = None
    ) -> List[Dict]:
        """
        Search BookStack content with optional chunk-based retrieval

        Args:
            query: Search query
            limit: Maximum results
            use_chunks: Whether to use chunk-based search (auto-detect if None)

        Returns:
            List of search results
        """
        # Auto-detect chunking availability
        if use_chunks is None:
            use_chunks = self.enable_chunking and self._has_chunks()

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            if use_chunks:
                # Enhanced chunk-based search
                cursor.execute(
                    """
                    SELECT
                        bc.bookstack_id,
                        bc.content_type as type,
                        bc.title,
                        bc.url,
                        bc.chunk_index,
                        bc.word_count,
                        snippet(bookstack_chunks_fts, 1, '<mark>', '</mark>', '...', 50) as snippet,
                        'chunk' as result_type
                    FROM bookstack_chunks_fts
                    JOIN bookstack_chunks bc ON bookstack_chunks_fts.rowid = bc.id
                    WHERE bookstack_chunks_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                """,
                    (query, limit),
                )
            else:
                # Original content-based search
                cursor.execute(
                    """
                    SELECT
                        bc.bookstack_id,
                        bc.type,
                        bc.title,
                        bc.url,
                        NULL as chunk_index,
                        NULL as word_count,
                        snippet(bookstack_fts, 1, '<mark>', '</mark>', '...', 30) as snippet,
                        'content' as result_type
                    FROM bookstack_fts
                    JOIN bookstack_content bc ON bookstack_fts.rowid = bc.id
                    WHERE bookstack_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                """,
                    (query, limit),
                )

            results = []
            for row in cursor.fetchall():
                results.append(dict(row))

            logger.debug(
                f"Search '{query}' returned {len(results)} results ({'chunks' if use_chunks else 'content'})"
            )
            return results

    def search_chunks(
        self, query: str, limit: int = 10, content_type: str = None
    ) -> List[Dict]:
        """
        Search specifically in chunks with optional content type filtering

        Args:
            query: Search query
            limit: Maximum results
            content_type: Filter by content type ('page', 'chapter', 'book')

        Returns:
            List of chunk search results
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            base_query = """
                SELECT
                    bc.bookstack_id,
                    bc.content_type,
                    bc.title,
                    bc.url,
                    bc.chunk_index,
                    bc.word_count,
                    bc.book_id,
                    bc.chapter_id,
                    snippet(bookstack_chunks_fts, 1, '<mark>', '</mark>', '...', 50) as snippet
                FROM bookstack_chunks_fts
                JOIN bookstack_chunks bc ON bookstack_chunks_fts.rowid = bc.id
                WHERE bookstack_chunks_fts MATCH ?
            """

            params = [query]

            if content_type:
                base_query += " AND bc.content_type = ?"
                params.append(content_type)

            base_query += " ORDER BY rank LIMIT ?"
            params.append(limit)

            cursor.execute(base_query, params)

            results = []
            for row in cursor.fetchall():
                results.append(dict(row))

            return results

    def _has_chunks(self) -> bool:
        """Check if chunks are available in the database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM bookstack_chunks LIMIT 1")
                return cursor.fetchone()[0] > 0
        except Exception:
            return False

    def get_sync_stats(self) -> Dict:
        """
        Get synchronization statistics including chunk data

        Returns:
            Dict with content counts, chunk stats and last sync time
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Count by type (original content)
            cursor.execute("""
                SELECT type, COUNT(*) as count
                FROM bookstack_content
                GROUP BY type
            """)

            counts = {row[0]: row[1] for row in cursor.fetchall()}

            # Count chunks by content type
            chunk_counts = {}
            if self.enable_chunking:
                cursor.execute("""
                    SELECT content_type, COUNT(*) as count
                    FROM bookstack_chunks
                    GROUP BY content_type
                """)
                chunk_counts = {row[0]: row[1] for row in cursor.fetchall()}

            # Get last sync time
            cursor.execute("""
                SELECT MAX(synced_at) FROM bookstack_content
            """)

            last_sync = cursor.fetchone()[0]

            # Chunking statistics
            chunking_stats = {}
            if self.enable_chunking and chunk_counts:
                cursor.execute("""
                    SELECT
                        COUNT(*) as total_chunks,
                        AVG(word_count) as avg_words_per_chunk,
                        MIN(word_count) as min_words,
                        MAX(word_count) as max_words,
                        SUM(word_count) as total_words
                    FROM bookstack_chunks
                """)

                stats_row = cursor.fetchone()
                if stats_row:
                    chunking_stats = {
                        "total_chunks": stats_row[0],
                        "avg_words_per_chunk": round(stats_row[1] or 0, 1),
                        "min_words": stats_row[2] or 0,
                        "max_words": stats_row[3] or 0,
                        "total_words": stats_row[4] or 0,
                        "chunks_by_type": chunk_counts,
                    }

            return {
                "content_counts": counts,
                "chunk_stats": chunking_stats,
                "last_sync": last_sync,
                "total_content": sum(counts.values()),
                "chunking_enabled": self.enable_chunking,
            }
