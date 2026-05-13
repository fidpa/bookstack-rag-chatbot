"""
Context building service for chat
Dual-RAG: BookStack + Knowledge Base Integration
"""

import logging

logger = logging.getLogger(__name__)

# BookStack integration for context
try:
    from bookstack.sync_service import BookStackSyncService
except ImportError:
    BookStackSyncService = None

# Knowledge Base integration for document RAG
try:
    from documents.knowledge_base.services import ContextService as KBContextService
except ImportError:
    KBContextService = None
    logger.warning("Knowledge Base ContextService not available - KB RAG disabled")


class ChatContextBuilder:
    """Service for building context from BookStack + Knowledge Base (Dual-RAG)"""

    @classmethod
    def build_combined_context(cls, user_message: str, bookstack_context: dict = None) -> str:
        """
        Build context from BookStack + Knowledge Base (Dual-RAG)

        Args:
            user_message: User's message
            bookstack_context: BookStack page context passed from widget

        Returns:
            Combined context string from BookStack + KB
        """
        combined_context = ""

        # 1. BookStack context (primary source - wiki content)
        if bookstack_context:
            try:
                page_title = bookstack_context.get('title', 'Unknown Page')
                page_content = bookstack_context.get('content', '')
                page_url = bookstack_context.get('url', '')

                if page_content:
                    combined_context = f"BookStack Page: {page_title}\n"
                    if page_url:
                        combined_context += f"URL: {page_url}\n"
                    combined_context += f"Content:\n{page_content[:2000]}..."  # Limit to 2000 chars
                    logger.info(f"Added BookStack page context: {page_title} ({len(page_content)} chars)")

            except Exception as e:
                logger.error(f"Error processing BookStack context: {str(e)}")

        # Fallback: Search BookStack content if sync service is available
        if not combined_context and BookStackSyncService:
            try:
                # Search relevant BookStack content
                search_results = BookStackSyncService.search_content(user_message, limit=3)
                if search_results:
                    context_parts = []
                    for result in search_results:
                        context_parts.append(f"Page: {result.get('title', 'Unknown')}\n{result.get('content', '')[:500]}...")
                    combined_context = "\n\n---\n\n".join(context_parts)
                    logger.info(f"Added BookStack search context ({len(combined_context)} chars)")
            except Exception as e:
                logger.error(f"Error searching BookStack content: {str(e)}")

        # 2. Knowledge Base context (secondary source - uploaded documents/PDFs)
        if KBContextService:
            try:
                logger.debug(f"Searching Knowledge Base for: {user_message}")
                kb_context = KBContextService.build_knowledge_context(
                    user_query=user_message,
                    max_docs=3,
                    use_chunks=True
                )

                if kb_context:
                    # Combine BookStack + KB contexts
                    if combined_context:
                        combined_context += "\n\n--- Knowledge Base Documents ---\n\n"
                    combined_context += kb_context
                    logger.info(f"Added Knowledge Base context ({len(kb_context)} chars)")
                else:
                    logger.debug("No relevant KB documents found")

            except Exception as e:
                logger.error(f"Error searching Knowledge Base: {str(e)}", exc_info=True)

        return combined_context
    
    @classmethod
    def create_context_message(cls, combined_context: str) -> dict:
        """
        Create a system message with Dual-RAG context (BookStack + KB)

        Args:
            combined_context: The combined context string (BookStack + KB)

        Returns:
            System message dict
        """
        if combined_context:
            return {
                'role': 'system',
                'content': f'KONTEXT: Du hast Zugriff auf zwei Wissensquellen:\n1. BookStack Wiki-Seiten (Team-Dokumentation)\n2. Hochgeladene Dokumente/PDFs (Spezialwissen)\n\nRelevanter Inhalt:\n\n{combined_context}\n\nBitte beantworte die Frage basierend auf diesem Kontext. Beziehe dich konkret auf die Quellen wenn möglich.'
            }
        else:
            return {
                'role': 'system',
                'content': 'Du bist ein hilfreicher Assistent für BookStack und Wissensdokumente. Beantworte Fragen präzise und hilfreich.'
            }