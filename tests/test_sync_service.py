"""The BookStack index: schema, sync walk, updates, deletes and pruning."""

import sqlite3

import pytest

from bookstack import sync_service
from bookstack.api_client import BookStackAPIError
from bookstack.sync_service import ContentSyncService, ensure_bookstack_schema
from conftest import fts_integrity, fts_match


def rows(db):
    return db.execute(
        "SELECT bookstack_id, type, title FROM bookstack_content ORDER BY type, bookstack_id"
    ).fetchall()


def test_full_sync_walks_book_contents(sync, db):
    # Regression: sync_book read book["chapters"] and book["pages"], which the
    # API does not return, so only the book row was indexed.
    stats = sync.sync_all()
    assert stats == {"books": 1, "chapters": 1, "pages": 2, "removed": 0, "errors": 0}
    assert rows(db) == [
        (1, "book", "Handbook"),
        (1, "chapter", "HR"),
        (1, "page", "Setup"),
        (2, "page", "Leave"),
    ]


def test_same_id_of_different_types_coexists(sync, db):
    # Regression: bookstack_id was UNIQUE on its own; book 1 replaced page 1.
    sync.sync_all()
    assert {t for i, t, _ in rows(db) if i == 1} == {"book", "chapter", "page"}


def test_chunks_are_stored(sync, db):
    # Regression: chunks were written on a second connection that waited for
    # the first one's lock, timed out after 5 s, and the error was swallowed.
    sync.sync_all()
    texts = [r[0] for r in db.execute("SELECT chunk_text FROM bookstack_chunks")]
    assert any("Port 8080" in t for t in texts)
    assert any("thirty days" in t for t in texts)


def test_update_replaces_terms_in_both_indexes(sync, db, fake_bookstack):
    # Regression: the FTS triggers did not remove old terms, so a query for a
    # word only the old version contained failed with "database disk image is
    # malformed".
    sync.sync_all()
    fake_bookstack.pages[1]["html"] = "<p>Install the agent with dnf.</p>"
    sync.sync_page(1)

    for table in ("bookstack_fts", "bookstack_chunks_fts"):
        assert fts_match(db, table, "apt") == []
        assert fts_match(db, table, "dnf") != []
        fts_integrity(db, table)


def test_deleting_a_chapter_removes_its_pages(sync, db):
    sync.sync_all()
    sync.remove_chapter_from_index(1)
    assert (2, "page", "Leave") not in rows(db)
    assert fts_match(db, "bookstack_chunks_fts", "thirty") == []
    fts_integrity(db, "bookstack_fts")


def test_deleting_a_book_removes_everything_in_it(sync, db):
    sync.sync_all()
    sync.remove_book_from_index(1)
    assert rows(db) == []
    assert db.execute("SELECT COUNT(*) FROM bookstack_chunks").fetchone()[0] == 0


def test_prune_removes_content_bookstack_no_longer_has(sync, db):
    sync.sync_all()
    sync._store_content(99, "page", "Gone", "stale text", "", 1, None, [])
    assert sync.sync_all()["removed"] == 1
    assert (99, "page", "Gone") not in rows(db)


def test_prune_is_skipped_when_an_item_fails_to_load(sync, db, fake_bookstack):
    # A chapter that times out must not be pruned as if it had been deleted.
    sync.sync_all()
    sync._store_content(99, "page", "Kept", "text", "", 1, None, [])
    fake_bookstack.chapters.clear()
    stats = sync.sync_all()
    assert stats["errors"] == 1 and stats["removed"] == 0
    assert (99, "page", "Kept") in rows(db)


def test_a_failed_book_listing_is_an_error_and_prunes_nothing(
    sync, db, fake_bookstack, monkeypatch
):
    # An unreachable BookStack must not look like an empty wiki.
    sync.sync_all()

    def refuse():
        raise BookStackAPIError("API request failed: refused")

    monkeypatch.setattr(fake_bookstack, "get_all_books", refuse)
    stats = sync.sync_all()
    assert stats["errors"] == 1 and stats["removed"] == 0
    assert len(rows(db)) == 4


def test_an_empty_wiki_is_not_an_error(sync, fake_bookstack):
    fake_bookstack.books.clear()
    assert sync.sync_all()["errors"] == 0


def test_urls_come_from_contents_or_are_derived(sync, db):
    sync.sync_all()
    urls = dict(
        ((i, t), u)
        for i, t, u in db.execute(
            "SELECT bookstack_id, type, url FROM bookstack_content"
        )
    )
    assert urls[(1, "page")] == "https://wiki.example.com/books/handbook/page/setup"
    assert urls[(2, "page")] == "https://wiki.example.com/link/2"
    assert urls[(1, "book")] == "https://wiki.example.com/books/handbook"
    assert urls[(1, "chapter")] == "https://wiki.example.com/books/handbook/chapter/hr"


def test_drafts_are_not_indexed(sync, db, fake_bookstack):
    fake_bookstack.pages[1]["draft"] = True
    sync.sync_all()
    assert (1, "page", "Setup") not in rows(db)


def test_legacy_schema_is_replaced(tmp_path):
    path = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE bookstack_content (id INTEGER PRIMARY KEY, "
        "bookstack_id INTEGER UNIQUE NOT NULL, type TEXT NOT NULL, title TEXT NOT NULL)"
    )
    conn.commit()
    conn.close()

    assert ensure_bookstack_schema(path) is True
    sync_service._schema_checked.discard(path)
    assert ensure_bookstack_schema(path) is False

    conn = sqlite3.connect(path)
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'bookstack_content'"
    ).fetchone()[0]
    assert "UNIQUE(bookstack_id, type)" in sql


@pytest.mark.parametrize("enable_chunking", [True, False])
def test_stats_report_counts(db_path, fake_bookstack, enable_chunking):
    service = ContentSyncService(fake_bookstack, db_path, enable_chunking)
    service.sync_all()
    stats = service.get_sync_stats()
    assert stats["total_content"] == 4
    assert bool(stats["chunk_stats"]) is enable_chunking
