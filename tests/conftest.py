"""Shared fixtures. Runs without BookStack, an LLM or Docker.

DATABASE_PATH is pointed at a temporary directory before any application
module is imported, because a few of them resolve paths at import time.
"""

import atexit
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "chatbot"))

_TMP = tempfile.mkdtemp(prefix="rag-chatbot-tests-")
atexit.register(shutil.rmtree, _TMP, ignore_errors=True)
os.environ["DATABASE_PATH"] = os.path.join(_TMP, "chatbot.db")
for var in ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "ALLOWED_VPN_IPS"):
    os.environ.pop(var, None)
os.environ["ENABLE_OLLAMA_FALLBACK"] = "false"
os.environ["BOOKSTACK_EXTERNAL_URL"] = "https://wiki.example.com"


@pytest.fixture
def db_path():
    """A fresh, empty database with the full schema, for each test."""
    from bookstack import sync_service
    from startup_migrations import run_startup_migrations

    path = os.environ["DATABASE_PATH"]
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(path + suffix):
            os.remove(path + suffix)
    sync_service._schema_checked.clear()
    assert run_startup_migrations()
    return path


@pytest.fixture
def db(db_path):
    conn = sqlite3.connect(db_path)
    yield conn
    conn.close()


class FakeBookStack:
    """Stands in for BookStackClient, shaped like the BookStack REST API.

    One book (id 1) holding a top-level page (id 1) and a chapter (id 1) with
    one page (id 2): the same numeric id for a book, a chapter and a page is
    the normal case in BookStack, which numbers each type separately.

    The entries of `contents` carry `url`, `book_id` and `draft` like the real
    `books-read` response, and a chapter entry embeds its pages. Whether the
    real client's HTTP layer behaves the same is covered in test_api_client.py.
    """

    def __init__(self):
        self.pages = {
            1: {
                "id": 1,
                "name": "Setup",
                "book_id": 1,
                "chapter_id": 0,
                "html": "<h2>Install</h2><p>Install the agent with <b>apt</b>.</p>"
                "<ul><li>Port 8080</li><li>Use sudo</li></ul>",
            },
            2: {
                "id": 2,
                "name": "Leave",
                "book_id": 1,
                "chapter_id": 1,
                "html": "<p>Full-time staff get thirty days of annual leave.</p>",
            },
        }
        self.chapters = {
            1: {
                "id": 1,
                "name": "HR",
                "slug": "hr",
                "book_slug": "handbook",
                "book_id": 1,
                "description_html": "<p>People matters</p>",
                "pages": [{"id": 2}],
            }
        }
        self.books = {
            1: {
                "id": 1,
                "name": "Handbook",
                "slug": "handbook",
                "description_html": "<p>The company handbook</p>",
                "contents": [
                    {
                        "type": "page",
                        "id": 1,
                        "book_id": 1,
                        "chapter_id": 0,
                        "draft": False,
                        "url": "https://wiki.example.com/books/handbook/page/setup",
                    },
                    {
                        "type": "chapter",
                        "id": 1,
                        "book_id": 1,
                        "url": "https://wiki.example.com/books/handbook/chapter/hr",
                        "pages": [{"id": 2, "book_id": 1, "chapter_id": 1}],
                    },
                ],
            }
        }

    def get_all_books(self):
        return [{"id": i, "name": b["name"]} for i, b in self.books.items()]

    def get_book(self, book_id):
        return self.books.get(book_id)

    def get_chapter(self, chapter_id):
        return self.chapters.get(chapter_id)

    def get_page(self, page_id):
        return self.pages.get(page_id)

    def get_item(self, kind, item_id):
        from bookstack.api_client import BookStackAPIError

        item = {"page": self.pages, "chapter": self.chapters, "book": self.books}[
            kind
        ].get(item_id)
        if item is None:
            raise BookStackAPIError("404 Client Error", status=404, not_found=True)
        return item

    def hide_page(self, page_id):
        """What the token's user sees after the page is restricted for its role."""
        del self.pages[page_id]
        for chapter in self.chapters.values():
            chapter["pages"] = [p for p in chapter["pages"] if p["id"] != page_id]
        for book in self.books.values():
            book["contents"] = [
                {**c, "pages": [p for p in c.get("pages", []) if p["id"] != page_id]}
                for c in book["contents"]
                if not (c["type"] == "page" and c["id"] == page_id)
            ]

    def hide_chapter(self, chapter_id):
        for page in [p for p in self.pages.values() if p["chapter_id"] == chapter_id]:
            self.hide_page(page["id"])
        del self.chapters[chapter_id]
        for book in self.books.values():
            book["contents"] = [
                c
                for c in book["contents"]
                if not (c["type"] == "chapter" and c["id"] == chapter_id)
            ]


@pytest.fixture
def fake_bookstack():
    return FakeBookStack()


@pytest.fixture
def sync(db_path, fake_bookstack):
    from bookstack.sync_service import ContentSyncService

    return ContentSyncService(fake_bookstack, db_path=db_path)


def fts_integrity(conn, table):
    """Raises sqlite3.DatabaseError if the external-content index drifted."""
    conn.execute(f"INSERT INTO {table}({table}, rank) VALUES('integrity-check', 1)")


def fts_match(conn, table, term):
    return conn.execute(
        f"SELECT rowid FROM {table} WHERE {table} MATCH ?", (f'"{term}"',)
    ).fetchall()
