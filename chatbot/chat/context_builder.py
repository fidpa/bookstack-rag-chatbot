"""
Context building service for chat
Dual-RAG: BookStack + Knowledge Base Integration
"""

import logging
from typing import Any, Dict, Optional

# This one service covers both sources: HybridSearchService queries the
# bookstack_* tables alongside kb_*, so wiki pages and uploaded documents are
# ranked and fused together rather than retrieved on separate paths.
from documents.knowledge_base.services import ContextService as KBContextService

logger = logging.getLogger(__name__)


class ChatContextBuilder:
    """Service for building context from BookStack + Knowledge Base (Dual-RAG)"""

    #: Characters of the current page kept in the context block. The widget
    #: already truncates page_content at 20000 (getEnhancedBookStackContext()
    #: in bookstack-integration/widget.html); this is the server-side bound.
    PAGE_CONTEXT_CHARS = 20000

    #: Longest page title and URL taken from the widget's context. The client
    #: controls these fields, and both end up in the prompt and in the log.
    MAX_TITLE_CHARS = 300
    MAX_URL_CHARS = 2000

    @classmethod
    def clean_page_context(cls, raw: Any) -> Dict[str, str]:
        """
        The parts of the widget's page context that are used, each bounded.

        Anything that is not a dict, and every field that is not text, is dropped.
        The page text may be one character longer than PAGE_CONTEXT_CHARS so that
        build_combined_context() can still tell it was cut.
        """
        if not isinstance(raw, dict):
            return {}
        limits = {
            "title": cls.MAX_TITLE_CHARS,
            "url": cls.MAX_URL_CHARS,
            "page_content": cls.PAGE_CONTEXT_CHARS + 1,
        }
        cleaned: Dict[str, str] = {}
        for key, limit in limits.items():
            value = raw.get(key)
            if isinstance(value, str) and value:
                cleaned[key] = value[:limit]
        return cleaned

    @classmethod
    def build_combined_context(
        cls, user_message: str, bookstack_context: Optional[dict] = None
    ) -> str:
        """
        Build context from BookStack + Knowledge Base (Dual-RAG)

        Args:
            user_message: User's message
            bookstack_context: BookStack page context passed from widget

        Returns:
            Combined context string from BookStack + KB
        """
        combined_context = ""
        bookstack_context = cls.clean_page_context(bookstack_context)

        # 1. The page the visitor is looking at, as sent by the widget.
        #    The field is named page_content there; see
        #    getEnhancedBookStackContext() in bookstack-integration/widget.html.
        if bookstack_context:
            try:
                page_title = bookstack_context.get("title", "Unknown Page")
                page_content = bookstack_context.get("page_content") or ""
                page_url = bookstack_context.get("url", "")

                if page_content:
                    combined_context = f"BookStack Page: {page_title}\n"
                    if page_url:
                        combined_context += f"URL: {page_url}\n"
                    excerpt = page_content[: cls.PAGE_CONTEXT_CHARS]
                    if len(page_content) > cls.PAGE_CONTEXT_CHARS:
                        excerpt += "..."
                    combined_context += f"Content:\n{excerpt}"
                    logger.info(
                        f"Added BookStack page context: {page_title} ({len(page_content)} chars)"
                    )

            except Exception as e:
                logger.error(f"Error processing BookStack context: {str(e)}")

        # 2. Retrieved context: knowledge-base documents and BookStack pages,
        #    searched together by the hybrid search behind ContextService.
        #    ContextService returns '' on failure or when nothing matched.
        kb_context = KBContextService.build_knowledge_context(
            user_query=user_message, max_docs=3
        )
        if kb_context:
            if combined_context:
                combined_context += "\n\n--- Retrieved Documents ---\n\n"
            combined_context += kb_context

        return combined_context
