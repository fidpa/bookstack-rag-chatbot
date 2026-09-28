"""The BookStack webhook endpoint, with payloads shaped like BookStack's own."""

import hashlib
import hmac

import pytest

import bookstack.api_client
from bookstack import webhooks


@pytest.fixture
def client(db_path, fake_bookstack, monkeypatch):
    monkeypatch.setattr(bookstack.api_client, "_client_instance", fake_bookstack)
    from app import create_app

    return create_app().test_client()


def payload(event, item_id, **item):
    """BookStack's WebhookFormatter output, reduced to what the handler reads."""
    return {
        "event": event,
        "text": f"Someone did {event}",
        "url": f"https://wiki.example.com/link/{item_id}",
        "related_item": {"id": item_id, **item},
    }


def titles(db):
    return sorted(r[0] for r in db.execute("SELECT title FROM bookstack_content"))


def test_page_update_indexes_the_page(client, db):
    # Regression: the handler read related.page.id; BookStack sends related_item.
    r = client.post("/webhook/bookstack", json=payload("page_update", 2, book_id=1))
    assert r.status_code == 200 and r.json["status"] == "processed"
    assert titles(db) == ["Leave"]
    url = db.execute("SELECT url FROM bookstack_content").fetchone()[0]
    assert url == "https://wiki.example.com/link/2"


def test_page_update_invalidates_parent_caches(client, fake_bookstack):
    client.post(
        "/webhook/bookstack", json=payload("page_update", 2, book_id=1, chapter_id=1)
    )
    assert {"page_2", "book_1", "chapter_1"} <= set(fake_bookstack.invalidated)


def test_book_events_index_and_delete(client, db):
    client.post("/webhook/bookstack", json=payload("book_update", 1))
    assert titles(db) == ["HR", "Handbook", "Leave", "Setup"]
    client.post("/webhook/bookstack", json=payload("book_delete", 1))
    assert titles(db) == []


def test_chapter_delete_removes_its_pages(client, db):
    client.post("/webhook/bookstack", json=payload("book_update", 1))
    client.post("/webhook/bookstack", json=payload("chapter_delete", 1))
    assert titles(db) == ["Handbook", "Setup"]


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
    assert r.status_code == 200
