"""
Context building service for chat
Dual-RAG: BookStack + Knowledge Base Integration
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Knowledge Base integration for document RAG.
#
# This one service covers both sources: HybridSearchService queries the
# bookstack_* tables alongside kb_*, so wiki pages and uploaded documents are
# ranked and fused together rather than retrieved on separate paths.
try:
    from documents.knowledge_base.services import ContextService as KBContextService
except ImportError:
    KBContextService = None
    logger.warning("Knowledge Base ContextService not available - KB RAG disabled")


class ChatContextBuilder:
    """Service for building context from BookStack + Knowledge Base (Dual-RAG)"""

    #: Characters of the current page kept in the context block.
    PAGE_CONTEXT_CHARS = 2000

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
        if KBContextService:
            try:
                logger.debug(f"Searching Knowledge Base for: {user_message}")
                kb_context = KBContextService.build_knowledge_context(
                    user_query=user_message, max_docs=3, use_chunks=True
                )

                if kb_context:
                    if combined_context:
                        combined_context += "\n\n--- Retrieved Documents ---\n\n"
                    combined_context += kb_context
                    logger.info(
                        f"Added Knowledge Base context ({len(kb_context)} chars)"
                    )
                else:
                    logger.debug("No relevant KB documents found")

            except Exception as e:
                logger.error(f"Error searching Knowledge Base: {str(e)}", exc_info=True)

        return combined_context
