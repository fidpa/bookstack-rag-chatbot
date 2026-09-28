"""
BookStack API Client

Thin wrapper around the BookStack REST API with a small TTL cache.
"""

import os
import logging
import threading
import requests
from typing import List, Dict, Optional, Any
from functools import wraps
from time import time

logger = logging.getLogger(__name__)

# Seconds to wait for BookStack before giving up on a request. Webhook handling
# runs inside the request thread, so an unbounded wait would pin a waitress worker.
REQUEST_TIMEOUT = 30

# BookStack caps list endpoints at 500 items per request.
PAGE_SIZE = 500


class BookStackAPIError(Exception):
    """Custom exception for BookStack API errors"""

    pass


def with_fallback(func):
    """Log API failures and return None (single items) or [] (lists) instead."""

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except Exception as e:
            logger.error(f"BookStack API error in {func.__name__}: {e}")
            if func.__name__.startswith("get_all"):
                return []
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

        # Simple cache with TTL. The client is a process-wide singleton shared by
        # all waitress threads, hence the lock.
        self._cache: Dict[str, Any] = {}
        self._cache_ttl = 300  # 5 minutes
        self._cache_lock = threading.Lock()

        logger.info(f"BookStack client initialized for {self.base_url}")

    def _get_from_cache(self, key: str) -> Optional[Any]:
        """Get value from cache if not expired"""
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            value, timestamp = entry
            if time() - timestamp < self._cache_ttl:
                return value
            self._cache.pop(key, None)
            return None

    def _set_cache(self, key: str, value: Any):
        """Set value in cache with timestamp"""
        with self._cache_lock:
            self._cache[key] = (value, time())

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
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"BookStack API request failed: {e}")
            raise BookStackAPIError(f"API request failed: {e}")

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

    @with_fallback
    def get_all_books(self) -> List[Dict]:
        """Get all books"""
        cache_key = "all_books"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        books = self._get_paginated("books")
        self._set_cache(cache_key, books)
        return books

    @with_fallback
    def get_book(self, book_id: int) -> Optional[Dict]:
        """Get a book; its chapters and pages are listed under `contents`."""
        cache_key = f"book_{book_id}"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        book = self._make_request("GET", f"books/{book_id}")
        self._set_cache(cache_key, book)
        return book

    @with_fallback
    def get_page(self, page_id: int) -> Optional[Dict]:
        """Get specific page with content"""
        cache_key = f"page_{page_id}"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        page = self._make_request("GET", f"pages/{page_id}")
        self._set_cache(cache_key, page)
        return page

    @with_fallback
    def get_chapter(self, chapter_id: int) -> Optional[Dict]:
        """Get specific chapter with pages"""
        cache_key = f"chapter_{chapter_id}"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        chapter = self._make_request("GET", f"chapters/{chapter_id}")
        self._set_cache(cache_key, chapter)
        return chapter

    def invalidate_cache(self, key: Optional[str] = None):
        """
        Invalidate cache

        Args:
            key: Specific cache key to invalidate, or None for all
        """
        with self._cache_lock:
            if key:
                if self._cache.pop(key, None) is not None:
                    logger.debug(f"Cache invalidated for key: {key}")
            else:
                self._cache.clear()
                logger.debug("All cache invalidated")


# Singleton instance
_client_instance: Optional[BookStackClient] = None


def get_bookstack_client() -> BookStackClient:
    """Get or create singleton BookStack client instance"""
    global _client_instance
    if _client_instance is None:
        _client_instance = BookStackClient()
    return _client_instance
