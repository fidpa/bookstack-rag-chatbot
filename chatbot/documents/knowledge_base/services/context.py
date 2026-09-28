"""
Context Service for the knowledge base
Turns a user question into the retrieved-documents block of the prompt.
"""

import logging
from typing import Optional

from .search import SearchService
from .strategies.chunk_strategy import ChunkSelectionStrategy

logger = logging.getLogger(__name__)


class ContextService:
    """Retrieval entry point used by the chat context builder."""

    # Documents (wiki items or uploads) that contribute excerpts
    MAX_CONTEXT_DOCS = 3

    @classmethod
    def build_knowledge_context(
        cls, user_query: str, max_docs: Optional[int] = None
    ) -> str:
        """
        Search wiki and uploaded documents and format the best excerpts.

        Args:
            user_query: The user's question
            max_docs: Documents to include (default: MAX_CONTEXT_DOCS)

        Returns:
            Context block for the LLM, or '' if nothing relevant was found
        """
        if not user_query or not user_query.strip():
            return ""

        try:
            documents, total_count = SearchService.search_documents(
                query=user_query, per_page=max_docs or cls.MAX_CONTEXT_DOCS
            )
            logger.info(
                f"Hybrid search returned {len(documents)} of {total_count} documents"
            )
            if not documents:
                return ""
            return ChunkSelectionStrategy.build_context(documents, user_query)

        except Exception as e:
            logger.error(f"Building knowledge context failed: {e}", exc_info=True)
            return ""
