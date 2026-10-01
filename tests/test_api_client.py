"""The real BookStackClient against a stand-in for BookStack's HTTP API.

`FakeBookStack` in conftest replaces the client wholesale. These tests keep the
client (paging, error handling, timeouts, no caching) and replace only the wire.
"""

import copy
import sqlite3

import pytest
import requests

from bookstack import api_client
from bookstack.api_client import BookStackAPIError, BookStackClient
from bookstack.sync_service import ContentSyncService


class Wire:
    """Serves BookStack-shaped responses from a state that tests can change."""

    def __init__(self):
        self.calls = []
        self.book = {
            "id": 1,
            "name": "Ops",
            "slug": "ops",
            "description_html": "",
            "tags": [],
        }
        self.chapters = {
            10: {"id": 10, "book_id": 1, "name": "Ops", "slug": "ops"},
            11: {"id": 11, "book_id": 1, "name": "Docs", "slug": "docs"},
        }
        self.pages = {
            100: {
                "id": 100,
                "name": "Runbook",
                "book_id": 1,
                "chapter_id": 10,
                "draft": False,
                "html": "<p>restart the daemon</p>",
            },
            101: {
                "id": 101,
                "name": "Other",
                "book_id": 1,
                "chapter_id": 11,
                "draft": False,
                "html": "<p>other text here</p>",
            },
        }

    def request(self, method, endpoint, **kwargs):
        self.calls.append(endpoint)
        kind, _, ident = endpoint.partition("/")
        if kind == "books":
            contents = [
                {"type": "chapter", "id": c["id"], "book_id": 1, "url": f"u/{c['id']}"}
                for c in self.chapters.values()
            ]
            return {**self.book, "contents": contents}
        if kind == "chapters":
            chapter = copy.deepcopy(self.chapters[int(ident)])
            chapter["pages"] = [
                {"id": p["id"], "chapter_id": p["chapter_id"]}
                for p in self.pages.values()
                if p["chapter_id"] == chapter["id"]
            ]
            return chapter
        if kind == "pages":
            return copy.deepcopy(self.pages[int(ident)])
        raise KeyError(endpoint)


@pytest.fixture
def client():
    return BookStackClient(base_url="http://bookstack", token_id="id", token_secret="s")


def chapter_of(db_path, page_id):
    with sqlite3.connect(db_path) as conn:
        return conn.execute(
            "SELECT chapter_id FROM bookstack_content WHERE bookstack_id = ? AND type = 'page'",
            (page_id,),
        ).fetchone()


def test_every_read_reaches_bookstack(client, monkeypatch):
    # The client keeps no cache: a webhook must see BookStack as it is now.
    wire = Wire()
    monkeypatch.setattr(client, "_make_request", wire.request)
    client.get_page(100)
    wire.pages[100]["name"] = "Renamed"
    assert client.get_page(100)["name"] == "Renamed"
    assert wire.calls == ["pages/100", "pages/100"]


def test_a_second_book_sort_sees_a_page_moved_in_between(db_path, client, monkeypatch):
    # Regression: sync_book() read chapters and pages from a five-minute cache and
    # only the book itself was invalidated. A second book_sort within five minutes
    # kept the old chapter, and a later chapter_delete then removed a live page.
    wire = Wire()
    monkeypatch.setattr(client, "_make_request", wire.request)
    sync = ContentSyncService(client, db_path=db_path)

    sync.sync_book(1)  # first book_sort
    assert chapter_of(db_path, 100) == (10,)

    wire.pages[100]["chapter_id"] = 11  # the page moves to another chapter
    sync.sync_book(1)  # second book_sort, seconds later
    assert chapter_of(db_path, 100) == (11,)

    del wire.chapters[10]  # the now empty chapter is deleted
    sync.remove_chapter_from_index(10)
    assert chapter_of(db_path, 100) == (11,)


def test_book_list_is_paged_until_the_total(client, monkeypatch):
    books = [{"id": i} for i in range(1, 1201)]
    asked = []

    def fake(method, endpoint, params=None, **kwargs):
        asked.append((endpoint, params["count"], params["offset"]))
        start = params["offset"]
        return {"data": books[start : start + params["count"]], "total": len(books)}

    monkeypatch.setattr(client, "_make_request", fake)
    assert [b["id"] for b in client.get_all_books()] == list(range(1, 1201))
    assert asked == [("books", 500, 0), ("books", 500, 500), ("books", 500, 1000)]


def test_paging_follows_what_bookstack_returns(client, monkeypatch):
    # API_MAX_ITEM_COUNT can be lower than 500; the client must not assume 500.
    books = [{"id": i} for i in range(1, 251)]

    def fake(method, endpoint, params=None, **kwargs):
        start = params["offset"]
        return {"data": books[start : start + 100], "total": len(books)}

    monkeypatch.setattr(client, "_make_request", fake)
    assert len(client.get_all_books()) == 250


def test_an_unreachable_bookstack_raises_for_the_book_list(client, monkeypatch):
    def refuse(*args, **kwargs):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(client.session, "request", refuse)
    with pytest.raises(BookStackAPIError):
        client.get_all_books()


def test_a_refused_token_raises_for_the_book_list(client, monkeypatch):
    class Unauthorized:
        def raise_for_status(self):
            raise requests.exceptions.HTTPError("401 Client Error: Unauthorized")

    monkeypatch.setattr(client.session, "request", lambda *a, **k: Unauthorized())
    with pytest.raises(BookStackAPIError):
        client.get_all_books()


class Status:
    """A response with an error status, as requests builds it."""

    def __init__(self, code):
        self.status_code = code

    def raise_for_status(self):
        raise requests.exceptions.HTTPError(f"{self.status_code} Error", response=self)


@pytest.mark.parametrize("getter", ["get_book", "get_chapter", "get_page"])
@pytest.mark.parametrize("code", [403, 404])
def test_an_item_bookstack_refuses_reads_as_none(client, monkeypatch, getter, code):
    monkeypatch.setattr(client.session, "request", lambda *a, **k: Status(code))
    assert getattr(client, getter)(1) is None


@pytest.mark.parametrize("getter", ["get_book", "get_chapter", "get_page"])
def test_an_unreachable_bookstack_raises_for_a_single_item(client, monkeypatch, getter):
    # A caller must be able to tell "cannot be read" from "try again later".
    def refuse(*args, **kwargs):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(client.session, "request", refuse)
    with pytest.raises(BookStackAPIError) as raised:
        getattr(client, getter)(1)
    assert raised.value.status is None and raised.value.transient


@pytest.mark.parametrize(
    "code, transient",
    [(404, False), (429, True), (499, False), (500, True), (503, True)],
)
def test_the_error_carries_the_status(client, monkeypatch, code, transient):
    monkeypatch.setattr(client.session, "request", lambda *a, **k: Status(code))
    with pytest.raises(BookStackAPIError) as raised:
        client.get_all_books()
    assert raised.value.status == code
    assert raised.value.transient is transient


class NotJson:
    """A success status with a body that is not JSON, as from a login page."""

    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        raise requests.exceptions.JSONDecodeError("Expecting value", "<html>", 0)


def test_an_answer_without_json_is_not_worth_asking_again(client, monkeypatch):
    # A wrong BOOKSTACK_API_URL answers 200 with HTML. Regression: that counted as
    # "BookStack does not answer" and was retried.
    monkeypatch.setattr(client.session, "request", lambda *a, **k: NotJson())
    with pytest.raises(BookStackAPIError) as raised:
        client.get_all_books()
    assert raised.value.status == 200 and not raised.value.transient
    assert client.get_page(1) is None


def test_requests_carry_a_timeout_and_the_token(client, monkeypatch):
    seen = {}

    class Ok:
        def raise_for_status(self):
            pass

        def json(self):
            return {}

    def capture(method, url, **kwargs):
        seen.update(kwargs, url=url)
        return Ok()

    monkeypatch.setattr(client.session, "request", capture)
    client.get_page(7)
    assert seen["timeout"] == api_client.REQUEST_TIMEOUT == 30
    assert seen["url"] == "http://bookstack/api/pages/7"
    assert client.session.headers["Authorization"] == "Token id:s"


def test_the_shared_client_is_created_once(monkeypatch):
    monkeypatch.setattr(api_client, "_client_instance", None)
    assert api_client.get_bookstack_client() is api_client.get_bookstack_client()
