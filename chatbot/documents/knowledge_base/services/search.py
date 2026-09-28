"""
Search Service for the knowledge base
Entry point to the hybrid search over wiki content and uploaded documents.
"""

import logging
from typing import List, Tuple

from ..models import KnowledgeDocument
from .hybrid_search import HybridSearchService

logger = logging.getLogger(__name__)


class SearchService:
    """Service for searching the knowledge base"""

    @classmethod
    def search_documents(
        cls,
        query: str,
        page: int = 1,
        per_page: int = 20,
        active_only: bool = True,
    ) -> Tuple[List[KnowledgeDocument], int]:
        """
        Hybrid search with pagination.

        Args:
            query: Search query
            page: Page number, 1-based
            per_page: Results per page
            active_only: Only search active uploaded documents

        Returns:
            (documents, total_count)
        """
        if not query or not query.strip():
            return [], 0

        documents, total_count, search_info = HybridSearchService.search(
            query=query, page=page, per_page=per_page, active_only=active_only
        )
        logger.debug(
            f"Hybrid search: {search_info.get('unique_documents', 0)} unique documents"
        )
        return documents, total_count
