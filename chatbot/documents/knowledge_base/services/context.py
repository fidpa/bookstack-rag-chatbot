"""
Context Service für Knowledge Base
Integriert die Wissensbasis in den Chat-Kontext
"""

import logging
from typing import List, Dict, Optional

from utils.database import get_db_connection
from .search import SearchService
from .indexing import IndexingService
from .hybrid_search import HybridSearchService
from .strategies.chunk_strategy import ChunkSelectionStrategy
from .strategies.document_strategy import DocumentSelectionStrategy
from ..models import KnowledgeDocument

logger = logging.getLogger(__name__)

class ContextService:
    """Service für die Integration der Wissensbasis in Chat-Kontext"""
    
    # Maximale Anzahl von Dokumenten im Kontext
    MAX_CONTEXT_DOCS = 3
    
    # Maximale Länge des Kontexts pro Dokument (Zeichen)
    MAX_DOC_CONTEXT_LENGTH = 2000
    
    @classmethod
    def build_knowledge_context(cls, user_query: str, max_docs: int = None, use_chunks: bool = True) -> str:
        """
        Erstellt einen Kontext aus der Wissensbasis basierend auf der Nutzer-Anfrage
        
        Args:
            user_query: Die Anfrage des Nutzers
            max_docs: Maximale Anzahl von Dokumenten (default: MAX_CONTEXT_DOCS)
            use_chunks: Ob Chunk-basierter Context verwendet werden soll
            
        Returns:
            Formatierter Kontext-String für die LLM
        """
        if not user_query:
            return ""
        
        max_docs = max_docs or cls.MAX_CONTEXT_DOCS
        
        try:
            logger.debug(f"Building knowledge context for query: {user_query}")
            
            # Verwende neue Hybrid-Search
            search_result = SearchService.search_documents(
                query=user_query, 
                page=1,
                per_page=max_docs,
                active_only=True,
                use_hybrid=True
            )
            
            # Handle both return formats
            if len(search_result) == 3:
                documents, total_count, search_info = search_result
            else:
                documents, total_count = search_result
                search_info = {}
            
            logger.info(f"Hybrid search returned {len(documents) if documents else 0} documents (total: {total_count}) for query: {user_query}")
            
            if not documents:
                logger.info(f"Keine relevanten Dokumente für Query gefunden: {user_query}")
                return ""
            
            # Kontext aufbauen
            if use_chunks and documents:
                # Chunk-basierter Context
                return ChunkSelectionStrategy.build_context(documents, user_query)
            else:
                # Legacy Document-basierter Context
                return DocumentSelectionStrategy.build_context(documents, user_query)
            
        except Exception as e:
            logger.error(f"Fehler beim Erstellen des Knowledge-Kontexts: {str(e)}", exc_info=True)
            return ""
    
    
    @classmethod
    def get_relevant_keywords(cls, user_query: str) -> List[str]:
        """
        Extrahiert relevante Keywords aus der Nutzer-Anfrage
        
        Args:
            user_query: Die Anfrage des Nutzers
            
        Returns:
            Liste von Keywords
        """
        # Nutze den IndexingService für Keyword-Extraktion
        keywords = IndexingService.extract_keywords(user_query, max_keywords=5)
        return keywords
    
    @classmethod
    def combine_contexts(cls, knowledge_context: str, chat_context: str) -> str:
        """
        Kombiniert Wissensbasis-Kontext mit Chat-Dokument-Kontext
        
        Args:
            knowledge_context: Kontext aus der Wissensbasis
            chat_context: Kontext aus Chat-Dokumenten
            
        Returns:
            Kombinierter Kontext
        """
        parts = []
        
        if knowledge_context:
            parts.append(knowledge_context)
        
        if chat_context:
            if parts:  # Separator wenn beide Kontexte vorhanden
                parts.append("\n---\n")
            parts.append(chat_context)
        
        return "\n".join(parts)
    
    @classmethod
    def get_context_stats(cls, user_query: str) -> Dict:
        """
        Gibt Statistiken über den verfügbaren Kontext zurück
        
        Args:
            user_query: Die Anfrage des Nutzers
            
        Returns:
            Dictionary mit Statistiken
        """
        try:
            # Suche durchführen
            documents, total_count = SearchService.search_documents(
                query=user_query,
                page=1,
                per_page=10,
                active_only=True
            )
            
            # Keywords extrahieren
            keywords = cls.get_relevant_keywords(user_query)
            
            stats = {
                'total_relevant_docs': total_count,
                'context_docs_used': min(len(documents), cls.MAX_CONTEXT_DOCS),
                'keywords_found': keywords,
                'top_documents': [
                    {
                        'title': doc.title or doc.original_filename or 'Unbekannt',
                        'relevance_score': getattr(doc, 'rank', 0)
                    }
                    for doc in documents[:cls.MAX_CONTEXT_DOCS]
                ]
            }
            
            return stats
            
        except Exception as e:
            logger.error(f"Fehler beim Abrufen der Kontext-Statistiken: {str(e)}")
            return {
                'total_relevant_docs': 0,
                'context_docs_used': 0,
                'keywords_found': [],
                'top_documents': []
            }
    
