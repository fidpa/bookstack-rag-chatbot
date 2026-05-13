"""
Document-based context building strategy (legacy)
"""

import logging
from typing import List

from utils.database import get_db_connection
from ...models import KnowledgeDocument

logger = logging.getLogger(__name__)


class DocumentSelectionStrategy:
    """Strategy for building document-based context from knowledge base"""
    
    # Maximale Länge des Kontexts pro Dokument (Zeichen)
    MAX_DOC_CONTEXT_LENGTH = 2000
    
    @classmethod
    def build_context(cls, documents: List[KnowledgeDocument], user_query: str) -> str:
        """
        Erstellt einen dokumentbasierten Kontext
        
        Args:
            documents: Liste von gefundenen Dokumenten
            user_query: Original-Query des Nutzers
            
        Returns:
            Formatierter Kontext
        """
        context_parts = []
        context_parts.append("## Relevante Informationen aus der Wissensbasis:\n")
        
        for idx, doc in enumerate(documents, 1):
            logger.debug(f"Adding document {idx} to context: {doc.title or doc.original_filename}")
            doc_context = cls._format_document_context(doc, idx)
            context_parts.append(doc_context)
        
        full_context = "\n".join(context_parts)
        
        logger.info(f"Kontext mit {len(documents)} Dokumenten erstellt für Query: {user_query} (Länge: {len(full_context)} Zeichen)")
        logger.debug(f"Context preview: {full_context[:200]}...")
        return full_context
    
    @classmethod
    def _format_document_context(cls, doc, index: int) -> str:
        """
        Formatiert ein einzelnes Dokument für den Kontext
        
        Args:
            doc: KnowledgeDocument Objekt
            index: Index des Dokuments (für Nummerierung)
            
        Returns:
            Formatierter Dokument-Kontext
        """
        title = doc.title or doc.original_filename or 'Unbekannt'
        
        # Versuche zuerst das search_snippet
        snippet = getattr(doc, 'search_snippet', '')
        
        # Wenn kein Snippet vorhanden, hole Content aus der Datenbank
        if not snippet:
            logger.debug(f"No search snippet for doc {doc.id}, fetching full content")
            try:
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT content FROM kb_search_fts 
                        WHERE doc_id = ? 
                        LIMIT 1
                    ''', (doc.id,))
                    row = cursor.fetchone()
                    if row:
                        snippet = row['content'] or ''
                        logger.debug(f"Fetched content for doc {doc.id}: {len(snippet)} chars")
                    else:
                        logger.warning(f"No content found in search index for doc {doc.id}")
                        snippet = f"[Dokument {title} - Inhalt nicht im Index gefunden]"
            except Exception as e:
                logger.error(f"Error fetching content for doc {doc.id}: {str(e)}")
                snippet = f"[Fehler beim Abrufen des Inhalts für {title}]"
        
        # Snippet begrenzen falls zu lang
        if len(snippet) > cls.MAX_DOC_CONTEXT_LENGTH:
            snippet = snippet[:cls.MAX_DOC_CONTEXT_LENGTH] + "..."
        
        # Kontext formatieren
        context = f"""
### Dokument {index}: {title}
{snippet}
"""
        
        logger.debug(f"Formatted context for doc {doc.id}: {len(context)} chars")
        return context