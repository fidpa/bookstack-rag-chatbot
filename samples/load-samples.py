#!/usr/bin/env python3
"""Load (or remove) the Acme Inc. sample knowledge base into BookStack.

Reads credentials from environment variables — typically sourced from `.env`:

    BOOKSTACK_EXTERNAL_URL   e.g. http://localhost:6875
    BOOKSTACK_TOKEN_ID       BookStack API token id
    BOOKSTACK_TOKEN_SECRET   BookStack API token secret

Usage:
    python3 samples/load-samples.py            # create book + pages
    python3 samples/load-samples.py --delete   # remove the book and all pages

The script is idempotent: re-running with no flag will refuse to create duplicate
pages and exit with a non-zero status.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests

BOOK_NAME = "Acme Inc. Knowledge Base"
BOOK_DESCRIPTION = "Sample knowledge base used to demo the RAG chatbot."

SAMPLE_FILES = [
    ("acme-employee-handbook.md", "Employee Handbook"),
    ("acme-it-onboarding.md", "IT Onboarding"),
    ("acme-vacation-policy.md", "Vacation and Leave Policy"),
    ("acme-product-faq.md", "Acme Widget v3 — Customer FAQ"),
    ("acme-meeting-rooms.md", "Meeting Room Booking"),
]


def env(name: str) -> str:
    """Return a required environment variable or exit with a helpful message."""
    value = os.environ.get(name)
    if not value:
        sys.exit(f"error: environment variable {name} is not set")
    return value


def make_session() -> tuple[requests.Session, str]:
    base_url = env("BOOKSTACK_EXTERNAL_URL").rstrip("/")
    token_id = env("BOOKSTACK_TOKEN_ID")
    token_secret = env("BOOKSTACK_TOKEN_SECRET")

    session = requests.Session()
    session.headers["Authorization"] = f"Token {token_id}:{token_secret}"
    session.headers["Accept"] = "application/json"
    return session, base_url


def find_book(session: requests.Session, base_url: str) -> dict | None:
    response = session.get(f"{base_url}/api/books", params={"filter[name]": BOOK_NAME})
    response.raise_for_status()
    for book in response.json().get("data", []):
        if book["name"] == BOOK_NAME:
            return book
    return None


def create_book(session: requests.Session, base_url: str) -> dict:
    response = session.post(
        f"{base_url}/api/books",
        json={"name": BOOK_NAME, "description": BOOK_DESCRIPTION},
    )
    response.raise_for_status()
    return response.json()


def create_page(
    session: requests.Session, base_url: str, book_id: int, title: str, markdown: str
) -> dict:
    response = session.post(
        f"{base_url}/api/pages",
        json={"book_id": book_id, "name": title, "markdown": markdown},
    )
    response.raise_for_status()
    return response.json()


def delete_book(session: requests.Session, base_url: str, book_id: int) -> None:
    response = session.delete(f"{base_url}/api/books/{book_id}")
    response.raise_for_status()


def cmd_load(session: requests.Session, base_url: str) -> int:
    if find_book(session, base_url):
        print(
            f"error: a book called '{BOOK_NAME}' already exists. "
            f"Run with --delete first, or rename the existing book.",
            file=sys.stderr,
        )
        return 1

    book = create_book(session, base_url)
    print(f"created book #{book['id']}: {book['name']}")

    samples_dir = Path(__file__).resolve().parent
    for filename, title in SAMPLE_FILES:
        markdown = (samples_dir / filename).read_text(encoding="utf-8")
        page = create_page(session, base_url, book["id"], title, markdown)
        print(f"  + page #{page['id']}: {title}")

    print(f"done. open {base_url} to view the book.")
    return 0


def cmd_delete(session: requests.Session, base_url: str) -> int:
    book = find_book(session, base_url)
    if not book:
        print(f"no book called '{BOOK_NAME}' found — nothing to delete.")
        return 0
    delete_book(session, base_url, book["id"])
    print(f"deleted book #{book['id']}: {book['name']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--delete",
        action="store_true",
        help="remove the sample book and all its pages",
    )
    args = parser.parse_args()

    session, base_url = make_session()
    return cmd_delete(session, base_url) if args.delete else cmd_load(session, base_url)


if __name__ == "__main__":
    raise SystemExit(main())
