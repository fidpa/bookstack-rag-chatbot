"""Live check against a running BookStack. Skipped unless credentials are set:

    BOOKSTACK_API_URL=http://localhost:6875 BOOKSTACK_TOKEN_ID=... \
    BOOKSTACK_TOKEN_SECRET=... pytest -m integration
"""

import os

import pytest

from bookstack.api_client import BookStackClient

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("BOOKSTACK_TOKEN_ID"), reason="BOOKSTACK_TOKEN_ID not set"
    ),
]


@pytest.fixture(scope="module")
def client():
    return BookStackClient(
        base_url=os.getenv("BOOKSTACK_API_URL", "http://localhost:6875")
    )


def test_books_can_be_listed(client):
    assert isinstance(client.get_all_books(), list)


def test_book_read_lists_contents(client):
    books = client.get_all_books()
    if not books:
        pytest.skip("no books in this BookStack")
    book = client.get_book(books[0]["id"])
    assert "contents" in book
