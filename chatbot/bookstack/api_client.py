"""
BookStack API Client

Thin wrapper around the BookStack REST API. It deliberately keeps no cache: a
full walk reads every item once, and a webhook has to see BookStack as it is
now, so cached copies would only serve stale data.
"""

import os
import math
import logging
import threading
import time
import requests
from typing import List, Dict, Optional
from functools import wraps

logger = logging.getLogger(__name__)

# Seconds to wait for BookStack before giving up on a request. Webhook syncs run one
# after the other in a single worker thread, so an unbounded wait would stall them all.
REQUEST_TIMEOUT = 30

# BookStack caps list endpoints at 500 items per request by default.
PAGE_SIZE = 500

# BookStack answers at most 180 API requests per minute from one client address by
# default (API_REQUESTS_PER_MIN), then 429 with Retry-After, the seconds left in that
# minute. A full resync or a large book needs more requests than that, so a 429 is
# waited out here instead of failing the walk: up to RATE_LIMIT_WAITS times per request,
# each wait capped at RATE_LIMIT_MAX_WAIT seconds, RATE_LIMIT_FALLBACK_WAIT without a
# usable Retry-After. Every wait also holds up the webhook worker that runs the request.
RATE_LIMIT_WAITS = 5
RATE_LIMIT_MAX_WAIT = 60
RATE_LIMIT_FALLBACK_WAIT = 10


def _rate_limit_wait(response) -> float:
    """Seconds to wait after a 429: Retry-After plus one, within the limits above."""
    try:
        seconds = float(response.headers.get("Retry-After"))
    except (TypeError, ValueError):
        return float(RATE_LIMIT_FALLBACK_WAIT)
    if math.isnan(seconds):
        return float(RATE_LIMIT_FALLBACK_WAIT)
    # Retry-After counts whole seconds, so the minute can end up to a second later
    return min(max(seconds, 0.0), RATE_LIMIT_MAX_WAIT) + 1


def _is_bookstack_404(response) -> bool:
    """True if a 404 carries BookStack's own error body: {"error": {"code": 404}}."""
    try:
        return response.json()["error"]["code"] == 404
    except (ValueError, KeyError, TypeError):
        return False


class BookStackAPIError(Exception):
    """A failed BookStack API request.

    `status` is the HTTP status, or None when BookStack did not answer at all
    (refused connection, timeout). `not_found` is True only for a 404 that BookStack
    itself sent about an item (its JSON error body): the item is deleted or hidden
    from the token's user. A 404 page from a proxy or a wrong BOOKSTACK_API_URL is
    not that.
    """

    def __init__(
        self, message: str, status: Optional[int] = None, not_found: bool = False
    ):
        super().__init__(message)
        self.status = status
        self.not_found = not_found

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
            BookStackAPIError: If request fails, or still answers 429 after
                RATE_LIMIT_WAITS waits
        """
        url = f"{self.base_url}/api/{endpoint}"
        kwargs.setdefault("timeout", REQUEST_TIMEOUT)

        waits = 0
        while True:
            try:
                response = self.session.request(method, url, **kwargs)
                response.raise_for_status()
                break
            except requests.exceptions.RequestException as e:
                status = e.response.status_code if e.response is not None else None
                if status == 429 and waits < RATE_LIMIT_WAITS:
                    waits += 1
                    delay = _rate_limit_wait(e.response)
                    logger.warning(
                        f"BookStack API rate limit reached (429), asking for "
                        f"{endpoint} again in {delay:.0f} s "
                        f"(wait {waits} of {RATE_LIMIT_WAITS})"
                    )
                    time.sleep(delay)
                    continue
                logger.error(f"BookStack API request failed: {e}")
                raise BookStackAPIError(
                    f"API request failed: {e}",
                    status=status,
                    not_found=status == 404 and _is_bookstack_404(e.response),
                )

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

    def get_item(self, kind: str, item_id: int) -> Dict:
        """
        Read a page, chapter or book (`kind`: page, chapter, book).

        Unlike get_page() and the others it raises on every failure, so that a
        caller can tell a 404 (deleted, or hidden from the token's user) from a
        refused token or an unreachable BookStack.

        Raises:
            BookStackAPIError: If the request fails
        """
        return self._make_request("GET", f"{kind}s/{item_id}")


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
