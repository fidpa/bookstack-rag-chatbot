"""
BookStack API Client

Provides a Python wrapper for the BookStack REST API with fallback to local knowledge base.
"""

import os
import logging
import requests
from typing import List, Dict, Optional, Any
from functools import wraps
from time import time

logger = logging.getLogger(__name__)


class BookStackAPIError(Exception):
    """Custom exception for BookStack API errors"""
    pass


def with_fallback(func):
    """Decorator to handle API failures with graceful fallback"""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except Exception as e:
            logger.error(f"BookStack API error in {func.__name__}: {e}")
            # Return empty result instead of raising
            if 'search' in func.__name__:
                return []
            elif 'get_all' in func.__name__:
                return []
            elif 'get_' in func.__name__:
                return None
            return None
    return wrapper


class BookStackClient:
    """
    BookStack API Client
    
    Handles authentication and provides methods to interact with BookStack API.
    """
    
    def __init__(self, base_url: str = None, token_id: str = None, token_secret: str = None):
        """
        Initialize BookStack API client
        
        Args:
            base_url: BookStack instance URL
            token_id: API token ID
            token_secret: API token secret
        """
        self.base_url = base_url or os.getenv('BOOKSTACK_API_URL', 'http://bookstack:80')
        self.token_id = token_id or os.getenv('BOOKSTACK_TOKEN_ID', '')
        self.token_secret = token_secret or os.getenv('BOOKSTACK_TOKEN_SECRET', '')
        
        # Remove trailing slash
        self.base_url = self.base_url.rstrip('/')
        
        # Setup session with auth
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Token {self.token_id}:{self.token_secret}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
        
        # Simple cache with TTL
        self._cache = {}
        self._cache_ttl = 300  # 5 minutes
        
        logger.info(f"BookStack client initialized for {self.base_url}")
    
    def _get_from_cache(self, key: str) -> Optional[Any]:
        """Get value from cache if not expired"""
        if key in self._cache:
            value, timestamp = self._cache[key]
            if time() - timestamp < self._cache_ttl:
                return value
            else:
                del self._cache[key]
        return None
    
    def _set_cache(self, key: str, value: Any):
        """Set value in cache with timestamp"""
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
        
        try:
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"BookStack API request failed: {e}")
            raise BookStackAPIError(f"API request failed: {e}")
    
    @with_fallback
    def test_connection(self) -> bool:
        """Test if API connection works"""
        try:
            self._make_request('GET', 'docs')
            return True
        except Exception:
            return False

    @with_fallback
    def get_all_books(self) -> List[Dict]:
        """Get all books"""
        cache_key = 'all_books'
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached
            
        response = self._make_request('GET', 'books')
        books = response.get('data', [])
        self._set_cache(cache_key, books)
        return books
    
    @with_fallback
    def get_book(self, book_id: int) -> Optional[Dict]:
        """Get specific book with chapters and pages"""
        cache_key = f'book_{book_id}'
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached
            
        book = self._make_request('GET', f'books/{book_id}')
        self._set_cache(cache_key, book)
        return book
    
    @with_fallback
    def get_all_pages(self) -> List[Dict]:
        """Get all pages (metadata only)"""
        cache_key = 'all_pages'
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached
            
        response = self._make_request('GET', 'pages')
        pages = response.get('data', [])
        self._set_cache(cache_key, pages)
        return pages
    
    @with_fallback
    def get_page(self, page_id: int) -> Optional[Dict]:
        """Get specific page with content"""
        cache_key = f'page_{page_id}'
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached
            
        page = self._make_request('GET', f'pages/{page_id}')
        self._set_cache(cache_key, page)
        return page
    
    @with_fallback
    def get_page_content(self, page_id: int) -> Optional[str]:
        """Get page content as HTML"""
        page = self.get_page(page_id)
        if page:
            return page.get('html', '')
        return None
    
    @with_fallback
    def search(self, query: str, filters: Dict = None) -> List[Dict]:
        """
        Search BookStack content
        
        Args:
            query: Search query
            filters: Optional filters (type, book_id, etc.)
            
        Returns:
            List of search results
        """
        params = {'query': query}
        if filters:
            params.update(filters)
            
        response = self._make_request('GET', 'search', params=params)
        return response.get('data', [])
    
    @with_fallback
    def get_all_chapters(self) -> List[Dict]:
        """Get all chapters"""
        cache_key = 'all_chapters'
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached
            
        response = self._make_request('GET', 'chapters')
        chapters = response.get('data', [])
        self._set_cache(cache_key, chapters)
        return chapters
    
    @with_fallback
    def get_chapter(self, chapter_id: int) -> Optional[Dict]:
        """Get specific chapter with pages"""
        cache_key = f'chapter_{chapter_id}'
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached
            
        chapter = self._make_request('GET', f'chapters/{chapter_id}')
        self._set_cache(cache_key, chapter)
        return chapter
    
    def invalidate_cache(self, key: str = None):
        """
        Invalidate cache
        
        Args:
            key: Specific cache key to invalidate, or None for all
        """
        if key:
            if key in self._cache:
                del self._cache[key]
                logger.debug(f"Cache invalidated for key: {key}")
        else:
            self._cache.clear()
            logger.debug("All cache invalidated")
    
    @with_fallback
    def get_shelves(self) -> List[Dict]:
        """Get all shelves"""
        cache_key = 'all_shelves'
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached
            
        response = self._make_request('GET', 'shelves')
        shelves = response.get('data', [])
        self._set_cache(cache_key, shelves)
        return shelves
    
    @with_fallback
    def get_attachments(self, page_id: int) -> List[Dict]:
        """Get attachments for a page"""
        cache_key = f'attachments_{page_id}'
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached
            
        response = self._make_request('GET', 'attachments', params={'filter[uploaded_to]': page_id})
        attachments = response.get('data', [])
        self._set_cache(cache_key, attachments)
        return attachments


# Singleton instance
_client_instance = None


def get_bookstack_client() -> BookStackClient:
    """Get or create singleton BookStack client instance"""
    global _client_instance
    if _client_instance is None:
        _client_instance = BookStackClient()
    return _client_instance