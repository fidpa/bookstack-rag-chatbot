"""
BookStack API Client

Thin wrapper around the BookStack REST API. It deliberately keeps no cache: a
full walk reads every item once, and a webhook has to see BookStack as it is
now, so cached copies would only serve stale data.
"""

import os
import logging
import threading
import requests
from typing import List, Dict, Optional
from functools import wraps

logger = logging.getLogger(__name__)

# Seconds to wait for BookStack before giving up on a request. Webhook syncs run one
# after the other in a single worker thread, so an unbounded wait would stall them all.
REQUEST_TIMEOUT = 30

# BookStack caps list endpoints at 500 items per request by default.
PAGE_SIZE = 500


class BookStackAPIError(Exception):
    """A failed BookStack API request.

    `status` is the HTTP status, or None when BookStack did not answer at all
    (refused connection, timeout).
    """

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status

    @property
    def transient(self) -> bool:
        """True if asking again later may succeed: no answer, 429 or a 5xx."""
        return self.status is None or self.status == 429 or self.status >= 500


def with_fallback(func):
    """
    Return None instead of raising when BookStack refuses a single item (404, 403).

    A transient failure (see BookStackAPIError.transient) is raised, so that callers
    can tell "this item cannot be read" from "BookStack cannot be reached right now".
    """

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except Exception as e:
            if isinstance(e, BookStackAPIError) and e.transient:
                raise
            logger.error(f"BookStack API error in {func.__name__}: {e}")
            return None

    return wrapper


class BookStackClient:
    """
    BookStack API Client

    Handles authentication and provides methods to interact with BookStack API.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        token_id: Optional[str] = None,
        token_secret: Optional[str] = None,
    ):
        """
        Initialize BookStack API client

        Args:
            base_url: BookStack instance URL
            token_id: API token ID
            token_secret: API token secret
        """
        self.base_url: str = (
            base_url or os.getenv("BOOKSTACK_API_URL") or "http://bookstack:80"
        )
        self.token_id = token_id or os.getenv("BOOKSTACK_TOKEN_ID", "")
        self.token_secret = token_secret or os.getenv("BOOKSTACK_TOKEN_SECRET", "")

        # Remove trailing slash
        self.base_url = self.base_url.rstrip("/")

        # Setup session with auth
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Token {self.token_id}:{self.token_secret}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

        logger.info(f"BookStack client initialized for {self.base_url}")

    def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict:
        """
        Make HTTP request to BookStack API

        Args:
            method: HTTP method
            endpoint: API endpoint
            **kwargs: Additional request parameters

        Returns:
            JSON response

        Raises:
            BookStackAPIError: If request fails
        """
        url = f"{self.base_url}/api/{endpoint}"
        kwargs.setdefault("timeout", REQUEST_TIMEOUT)

        try:
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.error(f"BookStack API request failed: {e}")
            status = e.response.status_code if e.response is not None else None
            raise BookStackAPIError(f"API request failed: {e}", status=status)

        # A page that is not JSON (a login page, another site behind a wrong
        # BOOKSTACK_API_URL) carries a success status: asking again will not help.
        try:
            return response.json()
        except ValueError as e:
            logger.error(f"BookStack API answered {endpoint} with no JSON: {e}")
            raise BookStackAPIError(
                f"API answered HTTP {response.status_code} without JSON; "
                "check BOOKSTACK_API_URL",
                status=response.status_code,
            )

    def _get_paginated(self, endpoint: str) -> List[Dict]:
        """Fetch every item of a list endpoint, following count/offset paging."""
        items: List[Dict] = []
        offset = 0
        while True:
            response = self._make_request(
                "GET", endpoint, params={"count": PAGE_SIZE, "offset": offset}
            )
            data = response.get("data", [])
            items.extend(data)
            offset += len(data)
            if not data or offset >= response.get("total", offset):
                return items

    def get_all_books(self) -> List[Dict]:
        """
        Get all books.

        Raises:
            BookStackAPIError: If BookStack cannot be reached or refuses the
                token. An empty list therefore means an empty wiki, never a
                failed request.
        """
        return self._get_paginated("books")

    @with_fallback
    def get_book(self, book_id: int) -> Optional[Dict]:
        """Get a book; its chapters and pages are listed under `contents`."""
        return self._make_request("GET", f"books/{book_id}")

    @with_fallback
    def get_page(self, page_id: int) -> Optional[Dict]:
        """Get specific page with content"""
        return self._make_request("GET", f"pages/{page_id}")

    @with_fallback
    def get_chapter(self, chapter_id: int) -> Optional[Dict]:
        """Get specific chapter with pages"""
        return self._make_request("GET", f"chapters/{chapter_id}")


# Singleton instance
_client_instance: Optional[BookStackClient] = None
_client_lock = threading.Lock()


def get_bookstack_client() -> BookStackClient:
    """Get or create the process-wide BookStack client (thread-safe)"""
    global _client_instance
    with _client_lock:
        if _client_instance is None:
            _client_instance = BookStackClient()
        return _client_instance
