"""The BookStack webhook endpoint, with payloads shaped like BookStack's own."""

import hashlib
import hmac
import threading
import time

import pytest

import bookstack.api_client
from bookstack.api_client import BookStackAPIError
from bookstack import webhooks


@pytest.fixture
def client(db_path, fake_bookstack, monkeypatch):
    monkeypatch.setattr(bookstack.api_client, "_client_instance", fake_bookstack)
    # The real delays are seconds; the tests only need the order of events.
    monkeypatch.setattr(webhooks, "SYNC_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(webhooks, "RESTORE_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(webhooks, "RETRY_DELAYS", (0.01, 0.01, 0.01))
    # Page URLs remembered from another test's events
    webhooks._latest_url.clear()
    from app import create_app

    yield create_app().test_client()
    assert webhooks.worker.wait_idle(5), "a webhook job outlived its test"


def payload(event, item_id, url=None, **item):
    """BookStack's WebhookFormatter output, reduced to what the handler reads.

    `url` is the item's own URL, as BookStack builds it from the slugs: it is
    deliberately not the /link/{id} permalink the sync falls back to.
    """
    return {
        "event": event,
        "text": f"Someone did {event}",
        "url": url or f"https://wiki.example.com/books/handbook/page/item-{item_id}",
        "related_item": {"id": item_id, **item},
    }


def post(client, body, **kwargs):
    """Send a webhook and wait until the worker has finished what it queued."""
    response = client.post("/webhook/bookstack", json=body, **kwargs)
    assert webhooks.worker.wait_idle(5)
    return response


def titles(db):
    return sorted(r[0] for r in db.execute("SELECT title FROM bookstack_content"))


def test_page_update_indexes_the_page(client, db):
    # Regression: the handler read related.page.id; BookStack sends related_item.
    r = post(client, payload("page_update", 2, book_id=1))
    assert r.status_code == 202 and r.json["status"] == "queued"
    assert titles(db) == ["Leave"]


def test_the_payload_url_becomes_the_page_link(client, db):
    # The sync would fall back to https://wiki.example.com/link/2; the URL BookStack
    # sends is the one with the slugs, and it is the better link.
    url = "https://wiki.example.com/books/handbook/page/leave-policy"
    post(client, payload("page_update", 2, url=url))
    assert db.execute("SELECT url FROM bookstack_content").fetchone()[0] == url


def test_a_page_without_a_payload_url_gets_the_permalink(client, db):
    body = payload("page_update", 2)
    del body["url"]
    post(client, body)
    url = db.execute("SELECT url FROM bookstack_content").fetchone()[0]
    assert url == "https://wiki.example.com/link/2"


def test_book_events_index_and_delete(client, db):
    post(client, payload("book_update", 1))
    assert titles(db) == ["HR", "Handbook", "Leave", "Setup"]
    r = post(client, payload("book_delete", 1))
    assert r.status_code == 200 and r.json["status"] == "processed"
    assert titles(db) == []


def test_chapter_delete_removes_its_pages(client, db):
    post(client, payload("book_update", 1))
    post(client, payload("chapter_delete", 1))
    assert titles(db) == ["Handbook", "Setup"]


def test_deletions_are_applied_before_the_response(client, db, monkeypatch):
    # Removing needs nothing from BookStack, so it must not wait for the worker.
    post(client, payload("book_update", 1))
    monkeypatch.setattr(webhooks, "SYNC_DELAY_SECONDS", 60.0)
    client.post("/webhook/bookstack", json=payload("page_delete", 2))
    assert "Leave" not in titles(db)
    # Only the repeated removal is queued, and it is due at once (no sync delay)
    assert webhooks.worker.wait_idle(5)
    assert "Leave" not in titles(db)


def test_a_page_deleted_while_a_job_reads_it_does_not_come_back(
    client, db, fake_bookstack
):
    # A job reads page 2; before it stores it, BookStack deletes the page and the
    # delete webhook removes it from the index. Regression: the job then wrote the
    # page back, and only a full resync took it out again.
    post(client, payload("book_update", 1))
    real_get_page = fake_bookstack.get_page

    def get_page(page_id):
        page = real_get_page(page_id)
        if page_id == 2 and fake_bookstack.pages.pop(2, None):
            r = client.post("/webhook/bookstack", json=payload("page_delete", 2))
            assert r.status_code == 200
        return page

    fake_bookstack.get_page = get_page
    post(client, payload("page_update", 2))
    assert "Leave" not in titles(db)


def test_an_existing_page_that_cannot_be_read_is_not_retried(
    client, db, fake_bookstack
):
    # Only a new item can still be invisible because BookStack has not committed.
    # An existing one that reads as 404 is gone or hidden from the token's user.
    reads = []

    def get_page(page_id):
        reads.append(page_id)
        return None

    fake_bookstack.get_page = get_page
    r = post(client, payload("page_update", 2))
    assert r.status_code == 202
    assert len(reads) == 1


def test_giving_up_does_not_blame_a_restriction_it_cannot_know(
    client, fake_bookstack, caplog
):
    # The same path handles a refused token (401) and a failed write; the warning
    # must not claim the item was deleted or restricted.
    fake_bookstack.get_page = lambda page_id: None
    post(client, payload("page_update", 2))
    assert "page 2 could not be read or stored" in caplog.text
    assert "401" in caplog.text


@pytest.mark.parametrize(
    "event, getter",
    [
        ("chapter_update", "get_chapter"),
        ("book_update", "get_book"),
        ("book_sort", "get_book"),
    ],
)
def test_a_book_or_chapter_is_retried_while_bookstack_does_not_answer(
    client, db, fake_bookstack, event, getter
):
    real = getattr(fake_bookstack, getter)
    reads = []

    def unreachable_once(item_id):
        reads.append(item_id)
        if len(reads) == 1:
            raise BookStackAPIError("Connection refused", status=None)
        return real(item_id)

    setattr(fake_bookstack, getter, unreachable_once)
    post(client, payload(event, 1))
    assert len(reads) == 2
    assert "Leave" in titles(db)


def test_a_book_is_retried_when_only_one_of_its_pages_got_no_answer(
    client, db, fake_bookstack
):
    # The book reads fine, but BookStack stops answering before page 2. Regression:
    # the job counted as done, and page 2 stayed as it was.
    fake_bookstack.pages[2] = {**fake_bookstack.pages[2], "name": "Leave policy"}
    real_get_page = fake_bookstack.get_page
    reads = []

    def get_page(page_id):
        reads.append(page_id)
        if page_id == 2 and reads.count(2) == 1:
            raise BookStackAPIError("Connection refused", status=None)
        return real_get_page(page_id)

    fake_bookstack.get_page = get_page
    post(client, payload("book_update", 1))
    assert reads.count(2) == 2
    assert "Leave policy" in titles(db)


def test_a_retried_older_job_does_not_restore_an_old_url(
    client, db, fake_bookstack, monkeypatch
):
    # page_update fails while BookStack restarts; the page is moved meanwhile and
    # that event is synced first. Regression: the update's retry then stored the URL
    # from its own, older payload.
    monkeypatch.setattr(webhooks, "RETRY_DELAYS", (0.3, 0.3, 0.3))
    real_get_page = fake_bookstack.get_page
    down = threading.Event()
    down.set()

    def get_page(page_id):
        if down.is_set():
            raise BookStackAPIError("Connection refused", status=None)
        return real_get_page(page_id)

    fake_bookstack.get_page = get_page
    old = "https://wiki.example.com/books/handbook/page/old-slug"
    new = "https://wiki.example.com/books/handbook/page/new-slug"
    client.post("/webhook/bookstack", json=payload("page_update", 2, url=old))
    time.sleep(0.1)  # the update has failed once and waits for its retry
    down.clear()
    post(client, payload("page_move", 2, url=new))
    url = db.execute(
        "SELECT url FROM bookstack_content WHERE bookstack_id = 2 AND type = 'page'"
    ).fetchone()[0]
    assert url == new


def test_an_event_without_url_does_not_inherit_an_older_one(client, db):
    post(client, payload("page_update", 2, url="https://wiki.example.com/x/old"))
    body = payload("page_update", 2)
    del body["url"]
    post(client, body)
    url = db.execute(
        "SELECT url FROM bookstack_content WHERE bookstack_id = 2 AND type = 'page'"
    ).fetchone()[0]
    assert url == "https://wiki.example.com/link/2"
    post(client, payload("book_update", 1))  # books take their URL from the API
    assert list(webhooks._latest_url) == []


def test_an_update_is_retried_while_bookstack_does_not_answer(
    client, db, fake_bookstack
):
    # Regression (found live): BookStack restarting two seconds after a page_update
    # refused the read, and the edit stayed out of the index until a full resync.
    real_get_page = fake_bookstack.get_page
    reads = []

    def get_page(page_id):
        reads.append(page_id)
        if len(reads) < 3:
            raise BookStackAPIError("Connection refused", status=None)
        return real_get_page(page_id)

    fake_bookstack.get_page = get_page
    post(client, payload("page_update", 2))
    assert len(reads) == 3
    assert titles(db) == ["Leave"]


def test_missing_item_id_is_rejected(client):
    r = client.post(
        "/webhook/bookstack",
        json={"event": "page_update", "related": {"page": {"id": 1}}},
    )
    assert r.status_code == 400


def test_irrelevant_event_is_ignored(client):
    r = client.post("/webhook/bookstack", json=payload("bookshelf_update", 1))
    assert r.json["status"] == "ignored"


def test_signature_is_enforced_when_a_secret_is_set(client, monkeypatch):
    monkeypatch.setattr(webhooks, "WEBHOOK_SECRET", "s3cret")
    body = b'{"event": "page_update", "related_item": {"id": 2}}'
    assert client.post("/webhook/bookstack", data=body).status_code == 401

    signature = hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    r = client.post(
        "/webhook/bookstack",
        data=body,
        content_type="application/json",
        headers={"X-BookStack-Signature": signature},
    )
    assert r.status_code == 202
    assert webhooks.worker.wait_idle(5)


# --- BookStack sends create, move and sort events before its own commit ------------
# Live against BookStack 25.07.3, a receiver that reads the item back inside the
# webhook gets the draft for page_create, a 404 for chapter_create and the old parent
# for page_move. These tests script exactly that.


def test_the_response_does_not_wait_for_the_sync(client, db, fake_bookstack):
    release = threading.Event()
    real_get_page = fake_bookstack.get_page

    def slow(page_id):
        release.wait(5)
        return real_get_page(page_id)

    fake_bookstack.get_page = slow
    started = time.monotonic()
    r = client.post("/webhook/bookstack", json=payload("page_create", 2))
    assert r.status_code == 202 and time.monotonic() - started < 1.0
    assert titles(db) == []  # the worker is still waiting for BookStack
    release.set()
    assert webhooks.worker.wait_idle(5)
    assert titles(db) == ["Leave"]


def test_a_new_page_that_still_reads_as_a_draft_is_indexed_on_a_retry(
    client, db, fake_bookstack
):
    published = fake_bookstack.pages[2]
    reads = []

    def get_page(page_id):
        reads.append(page_id)
        # BookStack has not committed yet on the first two reads
        return (
            {**published, "draft": True, "name": "New Page"}
            if len(reads) < 3
            else published
        )

    fake_bookstack.get_page = get_page
    post(client, payload("page_create", 2, book_id=1, draft=False))
    assert len(reads) == 3
    assert titles(db) == ["Leave"]


def test_a_new_chapter_that_is_not_found_yet_is_indexed_on_a_retry(
    client, db, fake_bookstack
):
    chapter = fake_bookstack.chapters[1]
    reads = []

    def get_chapter(chapter_id):
        reads.append(chapter_id)
        return None if len(reads) < 2 else chapter

    fake_bookstack.get_chapter = get_chapter
    post(client, payload("chapter_create", 1, book_id=1))
    assert len(reads) == 2
    assert "HR" in titles(db)


def test_a_new_book_that_is_not_found_yet_is_indexed_on_a_retry(
    client, db, fake_bookstack
):
    # BookStack sends book_create from inside its transaction as well
    # (BookRepo::create), so the first read can miss the new book.
    book = fake_bookstack.books[1]
    reads = []

    def get_book(book_id):
        reads.append(book_id)
        return None if len(reads) < 2 else book

    fake_bookstack.get_book = get_book
    post(client, payload("book_create", 1))
    assert len(reads) == 2
    assert "Handbook" in titles(db)


def test_a_new_page_is_retried_even_when_a_book_with_its_id_is_indexed(
    client, db, fake_bookstack, sync
):
    # BookStack numbers books, chapters and pages separately, so page 1 sits next to
    # book 1 and chapter 1. Whether the new page is indexed yet must be asked for the
    # page, not for any row with that id.
    sync.sync_book(1)
    db.execute("DELETE FROM bookstack_content WHERE type = 'page'")
    db.commit()
    published = fake_bookstack.pages[1]
    reads = []

    def get_page(page_id):
        reads.append(page_id)
        return {**published, "draft": True} if len(reads) < 2 else published

    fake_bookstack.get_page = get_page
    post(client, payload("page_create", 1, draft=False))
    assert len(reads) == 2
    assert "Setup" in titles(db)


def test_a_moved_page_is_indexed_under_its_new_chapter(client, db, fake_bookstack):
    post(client, payload("book_update", 1))
    fake_bookstack.pages[1]["chapter_id"] = 1  # the page moves into chapter 1
    post(client, payload("page_move", 1, book_id=1, chapter_id=1))
    chapter = db.execute(
        "SELECT chapter_id FROM bookstack_content WHERE bookstack_id = 1 AND type = 'page'"
    ).fetchone()[0]
    assert chapter == 1


def test_a_real_draft_is_not_retried(client, db, fake_bookstack):
    reads = []
    draft = {**fake_bookstack.pages[2], "draft": True}

    def get_page(page_id):
        reads.append(page_id)
        return draft

    fake_bookstack.get_page = get_page
    post(client, payload("page_update", 2, draft=True))
    assert len(reads) == 1
    assert titles(db) == []


def test_it_gives_up_after_the_last_attempt(client, db, fake_bookstack, caplog):
    reads = []

    def get_page(page_id):
        reads.append(page_id)
        return None

    fake_bookstack.get_page = get_page
    r = post(client, payload("page_create", 2))
    assert r.status_code == 202
    assert len(reads) == 1 + len(webhooks.RETRY_DELAYS)
    assert "gave up" in caplog.text
    assert titles(db) == []


def test_restoring_from_the_recycle_bin_walks_the_wiki_without_pruning(
    client, db, sync
):
    # The event names no item. Regression: it was ignored, so a restored page,
    # chapter or book stayed out of the index.
    sync._store_content(
        99, "page", "Stray", "text", "", 1, None, []
    )  # not in BookStack
    r = post(
        client, {"event": "recycle_bin_restore", "url": "https://wiki.example.com/x"}
    )
    assert r.status_code == 202 and r.json["status"] == "queued"
    assert titles(db) == ["HR", "Handbook", "Leave", "Setup", "Stray"]


def test_a_restore_walk_is_not_repeated_for_one_item_that_fails(
    client, db, fake_bookstack, caplog
):
    # Walking the whole wiki again would hold up every other webhook; the item is
    # left to the next full resync.
    books = []
    real_get_book = fake_bookstack.get_book

    def get_book(book_id):
        books.append(book_id)
        return real_get_book(book_id)

    fake_bookstack.get_book = get_book
    del fake_bookstack.pages[2]  # listed in the chapter, but cannot be read
    post(client, {"event": "recycle_bin_restore", "url": "https://wiki.example.com/x"})
    assert books == [1]
    assert "Setup" in titles(db)
    assert "failed to load" in caplog.text


def test_a_restore_walk_is_repeated_when_bookstack_cannot_list_the_books(
    client, db, fake_bookstack
):
    real_get_all_books = fake_bookstack.get_all_books
    calls = []

    def get_all_books():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("BookStack is restarting")
        return real_get_all_books()

    fake_bookstack.get_all_books = get_all_books
    post(client, {"event": "recycle_bin_restore", "url": "https://wiki.example.com/x"})
    assert len(calls) == 2
    assert "Leave" in titles(db)


def test_a_restore_walk_of_an_empty_wiki_is_not_repeated(client, db, fake_bookstack):
    # No book and no error is a finished walk, not an unreachable BookStack.
    calls = []

    def get_all_books():
        calls.append(1)
        return []

    fake_bookstack.get_all_books = get_all_books
    post(client, {"event": "recycle_bin_restore", "url": "https://wiki.example.com/x"})
    assert calls == [1]


def test_a_full_queue_refuses_the_event_with_503(client, monkeypatch):
    monkeypatch.setattr(webhooks, "SYNC_DELAY_SECONDS", 60.0)
    monkeypatch.setattr(webhooks.worker, "_max_pending", 1)
    assert (
        client.post("/webhook/bookstack", json=payload("page_update", 1)).status_code
        == 202
    )
    r = client.post("/webhook/bookstack", json=payload("page_update", 2))
    assert r.status_code == 503
    # deletions do not use the queue and still go through
    assert (
        client.post("/webhook/bookstack", json=payload("page_delete", 1)).status_code
        == 200
    )
    with webhooks.worker._cv:  # do not wait a minute for the job that was queued
        webhooks.worker._heap.clear()
        webhooks.worker._pending = 0


def test_the_test_endpoint_lists_the_accepted_events(client):
    accepted = client.get("/webhook/bookstack/test").json["accepts"]
    assert "permissions_update" in accepted and len(accepted) == 15


def permissions(kind, item_id, slug="x"):
    """A permissions_update as BookStack 25.07 sends it: no type, only the URL."""
    url = {
        "page": f"https://wiki.example.com/books/handbook/page/{slug}",
        "chapter": f"https://wiki.example.com/books/handbook/chapter/{slug}",
        "book": "https://wiki.example.com/books/handbook",
        "shelf": f"https://wiki.example.com/shelves/{slug}",
    }[kind]
    return payload("permissions_update", item_id, url=url)


@pytest.mark.parametrize(
    "url, kind",
    [
        ("http://localhost:6875/books/b/page/p", "page"),
        ("http://localhost:6875/books/b/chapter/c", "chapter"),
        ("http://localhost:6875/books/b", "book"),
        ("https://example.com/wiki/books/b/", "book"),
        ("https://example.com/wiki/books/b/page/p", "page"),
        ("http://localhost:6875/shelves/s", None),
        ("http://localhost:6875/books", None),
        ("http://localhost:6875/books/b/page/p/revisions", None),
        (None, None),
    ],
)
def test_a_permissions_update_is_told_apart_by_its_url(url, kind):
    assert webhooks._permissions_target(url) == kind


def test_a_page_restricted_afterwards_leaves_the_index(client, db, fake_bookstack):
    # Regression: the event was not subscribed, and a restricted page stayed in the
    # answers until the next full resync.
    post(client, payload("book_update", 1))
    fake_bookstack.hide_page(2)
    r = post(client, permissions("page", 2))
    assert r.status_code == 202 and r.json["status"] == "queued"
    assert titles(db) == ["HR", "Handbook", "Setup"]
    assert not db.execute(
        "SELECT 1 FROM bookstack_chunks WHERE chapter_id = 1"
    ).fetchall()


def test_a_page_made_visible_enters_the_index(client, db):
    post(client, permissions("page", 2, slug="leave"))
    assert titles(db) == ["Leave"]
    url = db.execute("SELECT url FROM bookstack_content").fetchone()[0]
    assert url == "https://wiki.example.com/books/handbook/page/leave"


def test_a_restricted_chapter_leaves_with_its_pages(client, db, fake_bookstack):
    post(client, payload("book_update", 1))
    fake_bookstack.hide_chapter(1)
    post(client, permissions("chapter", 1))
    assert titles(db) == ["Handbook", "Setup"]


def test_a_restricted_book_leaves_with_everything_in_it(client, db, fake_bookstack):
    post(client, payload("book_update", 1))
    del fake_bookstack.books[1]
    post(client, permissions("book", 1))
    assert titles(db) == []


def test_a_visible_book_drops_what_is_hidden_inside_it(client, db, fake_bookstack):
    # Restricting a book can leave the book visible but hide a chapter or page in
    # it that does not override the book's permissions.
    post(client, payload("book_update", 1))
    fake_bookstack.hide_chapter(1)
    fake_bookstack.hide_page(1)
    post(client, permissions("book", 1))
    assert titles(db) == ["Handbook"]


def test_a_visible_chapter_drops_a_page_hidden_inside_it(client, db, fake_bookstack):
    post(client, payload("book_update", 1))
    fake_bookstack.hide_page(2)
    post(client, permissions("chapter", 1))
    assert titles(db) == ["HR", "Handbook", "Setup"]


def test_nothing_is_dropped_after_a_walk_with_errors(client, db, fake_bookstack):
    # A page that fails to load is missing from the walk like a hidden one; removing
    # it would be wrong, just as sync_all() does not prune after errors.
    post(client, payload("book_update", 1))
    fake_bookstack.get_page = lambda page_id: None
    post(client, permissions("book", 1))
    assert titles(db) == ["HR", "Handbook", "Leave", "Setup"]


def test_a_permissions_update_is_retried_while_bookstack_does_not_answer(
    client, db, fake_bookstack
):
    post(client, payload("book_update", 1))
    real = fake_bookstack.get_item
    reads = []

    def unreachable_once(kind, item_id):
        reads.append(item_id)
        if len(reads) == 1:
            raise BookStackAPIError("Connection refused", status=None)
        return real(kind, item_id)

    fake_bookstack.get_item = unreachable_once
    fake_bookstack.hide_page(2)
    post(client, permissions("page", 2))
    assert len(reads) == 2
    assert "Leave" not in titles(db)


@pytest.mark.parametrize("status", [401, 403, 500])
def test_only_a_404_removes_on_a_permissions_update(client, db, fake_bookstack, status):
    # A refused token (401), a token without API access (403) or a failing BookStack
    # says nothing about the item; dropping it would empty the index item by item.
    post(client, payload("book_update", 1))

    def fail(kind, item_id):
        raise BookStackAPIError(f"{status} Error", status=status)

    fake_bookstack.get_item = fail
    post(client, permissions("page", 2))
    assert "Leave" in titles(db)


def test_a_shelf_permissions_update_is_ignored(client, db):
    post(client, payload("book_update", 1))
    r = client.post("/webhook/bookstack", json=permissions("shelf", 1))
    assert r.status_code == 200 and r.json["status"] == "ignored"
    assert titles(db) == ["HR", "Handbook", "Leave", "Setup"]


@pytest.mark.parametrize("event", ["page_move", "page_update", "page_restore"])
def test_a_page_moved_out_of_sight_leaves_the_index(client, db, fake_bookstack, event):
    # Regression: a page moved into a book the token's user may not see read as
    # 404; the job gave up and the page stayed answerable until a full resync.
    post(client, payload("book_update", 1))
    fake_bookstack.hide_page(2)
    post(client, payload(event, 2))
    assert titles(db) == ["HR", "Handbook", "Setup"]


@pytest.mark.parametrize("event", ["chapter_move", "chapter_update"])
def test_a_chapter_moved_out_of_sight_leaves_with_its_pages(
    client, db, fake_bookstack, event
):
    post(client, payload("book_update", 1))
    fake_bookstack.hide_chapter(1)
    post(client, payload(event, 1))
    assert titles(db) == ["Handbook", "Setup"]


def test_a_new_page_that_is_not_found_is_not_removed(client, db, fake_bookstack):
    # A 404 after page_create only means BookStack has not committed yet.
    post(client, payload("book_update", 1))
    fake_bookstack.hide_page(2)
    post(client, payload("page_create", 2))
    assert "Leave" in titles(db)


@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_read_does_not_remove_on_an_update(
    client, db, fake_bookstack, status
):
    post(client, payload("book_update", 1))
    fake_bookstack.get_page = lambda page_id: None

    def refuse(kind, item_id):
        raise BookStackAPIError(f"{status} Error", status=status)

    fake_bookstack.get_item = refuse
    post(client, payload("page_update", 2))
    assert "Leave" in titles(db)


def test_an_update_whose_recheck_gets_no_answer_is_retried(client, db, fake_bookstack):
    post(client, payload("book_update", 1))
    real_get_item = fake_bookstack.get_item
    fake_bookstack.hide_page(2)
    checks = []

    def unreachable_once(kind, item_id):
        checks.append(item_id)
        if len(checks) == 1:
            raise BookStackAPIError("Connection refused", status=None)
        return real_get_item(kind, item_id)

    fake_bookstack.get_item = unreachable_once
    post(client, payload("page_move", 2))
    assert len(checks) == 2
    assert "Leave" not in titles(db)


def test_a_page_event_without_draft_counts_as_published(client, db, fake_bookstack):
    # Only an explicit draft flag means the author has not published yet. A page
    # event without one that still reads as a draft is retried like a published one.
    published = fake_bookstack.pages[2]
    reads = []

    def get_page(page_id):
        reads.append(page_id)
        return {**published, "draft": True} if len(reads) < 2 else published

    fake_bookstack.get_page = get_page
    post(client, payload("page_create", 2, book_id=1))
    assert len(reads) == 2
    assert titles(db) == ["Leave"]


def test_a_restore_waits_its_own_delay(client, monkeypatch):
    # The restore itself happens after the event, so its walk waits longer than an
    # item sync.
    delays = {}
    submit = webhooks.worker.submit

    def record(label, task, delay, retry_delays):
        delays[label] = delay
        submit(label, task, delay, retry_delays)

    monkeypatch.setattr(webhooks, "SYNC_DELAY_SECONDS", 0.01)
    monkeypatch.setattr(webhooks, "RESTORE_DELAY_SECONDS", 0.02)
    monkeypatch.setattr(webhooks.worker, "submit", record)
    post(client, {"event": "recycle_bin_restore", "url": "https://wiki.example.com/x"})
    post(client, payload("page_update", 2))
    assert delays == {"recycle_bin_restore": 0.02, "page_update #2": 0.01}


def test_a_page_the_index_keeps_under_an_old_book_is_not_removed(
    client, db, fake_bookstack
):
    # The index can hold a page under a book it has left (a book_sort of the old
    # book does not touch it). The book walk misses it; it must be asked for on its
    # own and kept, under its new book, instead of being pruned.
    post(client, payload("book_update", 1))
    fake_bookstack.pages[1]["book_id"] = 2
    fake_bookstack.books[1]["contents"] = [
        c for c in fake_bookstack.books[1]["contents"] if c["type"] != "page"
    ]
    post(client, permissions("book", 1))
    assert titles(db) == ["HR", "Handbook", "Leave", "Setup"]
    row = db.execute("SELECT book_id FROM bookstack_content WHERE title = 'Setup'")
    assert row.fetchone() == (2,)


def test_a_hidden_item_is_removed_even_if_another_failed_to_load(
    client, db, fake_bookstack, caplog
):
    # Each row the walk missed is checked on its own, so one page that fails to
    # load does not keep a restricted chapter answerable.
    post(client, payload("book_update", 1))
    fake_bookstack.hide_chapter(1)
    fake_bookstack.get_page = lambda page_id: None  # page 1 fails to load
    post(client, permissions("book", 1))
    assert titles(db) == ["Handbook", "Setup"]
    assert "permissions of book 1 changed" in caplog.text


def test_a_404_that_is_not_bookstacks_removes_nothing(client, db, fake_bookstack):
    post(client, payload("book_update", 1))

    def proxy_404(kind, item_id):
        raise BookStackAPIError("404 Client Error", status=404, not_found=False)

    fake_bookstack.get_item = proxy_404
    post(client, permissions("book", 1))
    post(client, payload("page_move", 2))
    assert titles(db) == ["HR", "Handbook", "Leave", "Setup"]


def test_a_permissions_update_stores_its_own_page_url(client, db):
    # A page event remembered an older URL; the permissions event carries the
    # current one and must win, as for any newer page event.
    post(
        client,
        payload("page_update", 2, url="https://wiki.example.com/books/old/page/a"),
    )
    post(client, permissions("page", 2, slug="new"))
    url = db.execute("SELECT url FROM bookstack_content").fetchone()[0]
    assert url == "https://wiki.example.com/books/handbook/page/new"


def test_only_rows_the_walk_missed_are_asked_for(client, db, fake_bookstack):
    # Every row is one more API request against BookStack's rate limit: a check
    # must stay inside the item, skip what the walk returned, and not ask again
    # for pages that went with their chapter.
    post(client, payload("book_update", 1))
    real_get_item = fake_bookstack.get_item
    asked = []

    def get_item(kind, item_id):
        asked.append((kind, item_id))
        return real_get_item(kind, item_id)

    fake_bookstack.get_item = get_item
    post(client, permissions("chapter", 1))
    post(client, permissions("book", 1))
    assert asked == [("chapter", 1), ("book", 1)]

    asked.clear()
    fake_bookstack.hide_chapter(1)
    post(client, permissions("book", 1))
    assert asked == [("book", 1), ("chapter", 1)]
    assert titles(db) == ["Handbook", "Setup"]
