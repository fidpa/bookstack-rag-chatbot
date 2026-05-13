"""
Search Implementation Functions
Contains the actual search implementations for different strategies
"""

import logging
from typing import List, Dict
from utils.database import get_db_connection
from ..query_processor import QueryProcessor, QueryAnalysis
from .strategies import SearchStrategy
from .models import SearchResult

logger = logging.getLogger(__name__)

class SearchImplementations:
    """Implementation of various search strategies"""
    
    # Gewichtung der verschiedenen Strategien
    STRATEGY_WEIGHTS = {
        SearchStrategy.TITLE_TAG: 3.0,      # Höchste Priorität
        SearchStrategy.EXACT_PHRASE: 2.5,
        SearchStrategy.KEYWORD_AND: 2.0,
        SearchStrategy.PROXIMITY: 1.8,
        SearchStrategy.KEYWORD_OR: 1.5,
        SearchStrategy.CHUNK_BASED: 1.3,
        SearchStrategy.FUZZY: 1.0          # Niedrigste Priorität
    }
    
    @classmethod
    def search_title_tags(cls, terms: List[str], active_only: bool) -> List[SearchResult]:
        """Sucht in Titel und Tags"""
        if not terms:
            return []
        
        results = []
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Erstelle WHERE-Klauseln für jeden Term
                where_clauses = []
                params = []
                
                for term in terms[:5]:  # Max 5 terms
                    where_clauses.append(
                        "(LOWER(d.title) LIKE ? OR LOWER(d.original_filename) LIKE ? OR "
                        "EXISTS (SELECT 1 FROM kb_tags t WHERE t.document_id = d.id AND LOWER(t.tag) LIKE ?))"
                    )
                    term_pattern = f'%{term.lower()}%'
                    params.extend([term_pattern, term_pattern, term_pattern])
                
                query = f'''
                    SELECT DISTINCT d.id, d.title, d.original_filename
                    FROM kb_documents d
                    WHERE ({' OR '.join(where_clauses)})
                    {'AND d.is_active = 1' if active_only else ''}
                '''
                
                cursor.execute(query, params)
                
                for row in cursor.fetchall():
                    results.append(SearchResult(
                        doc_id=row['id'],
                        doc_title=row['title'] or row['original_filename'],
                        doc_filename=row['original_filename'],
                        relevance_score=cls.STRATEGY_WEIGHTS[SearchStrategy.TITLE_TAG],
                        match_type=SearchStrategy.TITLE_TAG,
                        snippet=f"Treffer in Titel/Tags"
                    ))
                    
        except Exception as e:
            logger.error(f"Fehler bei Title/Tag-Suche: {str(e)}")
        
        return results
    
    @classmethod
    def search_exact_phrase(cls, phrase: str, active_only: bool) -> List[SearchResult]:
        """Sucht nach exakter Phrase in Chunks"""
        if not phrase:
            return []
        
        results = []
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # FTS5-Query vorbereiten
                fts_query = f'"{QueryProcessor.preprocess_for_fts5(phrase)}"'
                
                query = '''
                    SELECT
                        c.doc_id,
                        c.chunk_index,
                        c.chunk_text,
                        d.title,
                        d.original_filename,
                        snippet(kb_chunks_fts, 0, '<mark>', '</mark>', '...', 30) as snippet,
                        rank
                    FROM kb_chunks_fts fts
                    JOIN kb_chunks c ON fts.rowid = c.id
                    JOIN kb_documents d ON c.doc_id = d.id
                    WHERE kb_chunks_fts MATCH ?
                    AND (? = 0 OR d.is_active = 1)
                    ORDER BY rank
                    LIMIT 50
                '''
                
                cursor.execute(query, (fts_query, 1 if active_only else 0))
                
                # Gruppiere nach Dokument
                doc_results = {}
                for row in cursor.fetchall():
                    doc_id = row['doc_id']
                    if doc_id not in doc_results:
                        doc_results[doc_id] = SearchResult(
                            doc_id=doc_id,
                            doc_title=row['title'] or row['original_filename'],
                            doc_filename=row['original_filename'],
                            relevance_score=cls.STRATEGY_WEIGHTS[SearchStrategy.EXACT_PHRASE],
                            match_type=SearchStrategy.EXACT_PHRASE,
                            snippet=row['snippet']
                        )
                    
                    doc_results[doc_id].matched_chunks.append({
                        'chunk_index': row['chunk_index'],
                        'snippet': row['snippet'],
                        'rank': row['rank']
                    })
                
                results = list(doc_results.values())
                
        except Exception as e:
            logger.error(f"Fehler bei Exact Phrase-Suche: {str(e)}")
        
        return results
    
    @classmethod
    def search_keywords_or(cls, keywords: List[str], active_only: bool) -> List[SearchResult]:
        """Sucht mit OR-verknüpften Keywords"""
        if not keywords:
            return []
        
        results = []
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # FTS5-Query mit OR
                fts_terms = [QueryProcessor.preprocess_for_fts5(kw) for kw in keywords[:5]]
                fts_query = ' OR '.join(fts_terms)
                
                query = '''
                    WITH doc_matches AS (
                        SELECT 
                            c.doc_id,
                            d.title,
                            d.original_filename,
                            COUNT(*) as chunk_matches,
                            MIN(rank) as best_rank
                        FROM kb_chunks_fts fts
                        JOIN kb_chunks c ON fts.rowid = c.id
                        JOIN kb_documents d ON c.doc_id = d.id
                        WHERE kb_chunks_fts MATCH ?
                        AND (? = 0 OR d.is_active = 1)
                        GROUP BY c.doc_id, d.title, d.original_filename
                    ),
                    doc_snippets AS (
                        SELECT
                            c.doc_id,
                            snippet(kb_chunks_fts, 0, '<mark>', '</mark>', '...', 30) as snippet
                        FROM kb_chunks_fts fts
                        JOIN kb_chunks c ON fts.rowid = c.id
                        WHERE kb_chunks_fts MATCH ?
                        AND c.doc_id IN (SELECT doc_id FROM doc_matches)
                        LIMIT 1
                    )
                    SELECT 
                        dm.*,
                        COALESCE(ds.snippet, 'Match gefunden') as snippet
                    FROM doc_matches dm
                    LEFT JOIN doc_snippets ds ON dm.doc_id = ds.doc_id
                    ORDER BY dm.chunk_matches DESC, dm.best_rank
                    LIMIT 50
                '''
                
                cursor.execute(query, (fts_query, 1 if active_only else 0, fts_query))
                
                for row in cursor.fetchall():
                    # Score basiert auf Anzahl der Chunk-Matches
                    base_score = cls.STRATEGY_WEIGHTS[SearchStrategy.KEYWORD_OR]
                    score = base_score * (1 + min(row['chunk_matches'] / 10, 1))
                    
                    results.append(SearchResult(
                        doc_id=row['doc_id'],
                        doc_title=row['title'] or row['original_filename'],
                        doc_filename=row['original_filename'],
                        relevance_score=score,
                        match_type=SearchStrategy.KEYWORD_OR,
                        snippet=row['snippet']
                    ))
                    
        except Exception as e:
            logger.error(f"Fehler bei Keyword OR-Suche: {str(e)}")

        return results

    @classmethod
    def search_bookstack_content(cls, terms: List[str], active_only: bool = True) -> List[SearchResult]:
        """
        Sucht in BookStack Content (Titel und Inhalte)

        Args:
            terms: Suchbegriffe
            active_only: Aktuell nicht verwendet für BookStack

        Returns:
            Liste von SearchResult Objekten
        """
        if not terms:
            return []

        results = []
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()

                # Erstelle FTS5-Query für BookStack-Suche
                fts_query = ' OR '.join([QueryProcessor.preprocess_for_fts5(term) for term in terms[:5]])

                # Suche in BookStack FTS5 Tabelle
                query = '''
                    SELECT
                        bc.bookstack_id,
                        bc.type,
                        bc.title,
                        bc.url,
                        snippet(bookstack_fts, 1, '<mark>', '</mark>', '...', 50) as snippet,
                        'bookstack_' || bc.type as doc_type
                    FROM bookstack_fts fts
                    JOIN bookstack_content bc ON fts.rowid = bc.id
                    WHERE bookstack_fts MATCH ?
                    ORDER BY rank
                    LIMIT 10
                '''

                cursor.execute(query, (fts_query,))

                for row in cursor.fetchall():
                    results.append(SearchResult(
                        doc_id=f"bookstack_{row['bookstack_id']}_{row['type']}",  # Eindeutige ID
                        doc_title=row['title'],
                        doc_filename=f"BookStack {row['type'].title()}: {row['title']}",
                        relevance_score=cls.STRATEGY_WEIGHTS.get(SearchStrategy.KEYWORD_OR, 1.5) * 0.9,  # Etwas niedriger als KB
                        match_type=SearchStrategy.KEYWORD_OR,
                        snippet=row['snippet'] or f"BookStack {row['type']}: {row['title']}",
                        metadata={
                            'source': 'bookstack',
                            'bookstack_id': row['bookstack_id'],
                            'content_type': row['type'],
                            'url': row['url']
                        }
                    ))

        except Exception as e:
            logger.error(f"Fehler bei BookStack Content-Suche: {str(e)}")

        return results

    @classmethod
    def search_bookstack_chunks(cls, terms: List[str], active_only: bool = True) -> List[SearchResult]:
        """
        Sucht in BookStack Chunks für präzisere Kontextfindung

        Args:
            terms: Suchbegriffe
            active_only: Aktuell nicht verwendet für BookStack

        Returns:
            Liste von SearchResult Objekten
        """
        if not terms:
            return []

        results = []
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()

                # Erstelle FTS5-Query für BookStack-Chunks
                fts_query = ' OR '.join([QueryProcessor.preprocess_for_fts5(term) for term in terms[:5]])

                # Suche in BookStack Chunks FTS5 Tabelle
                query = '''
                    SELECT
                        bc.bookstack_id,
                        bc.content_type,
                        bc.title,
                        bc.url,
                        bc.chunk_index,
                        bc.word_count,
                        snippet(bookstack_chunks_fts, 1, '<mark>', '</mark>', '...', 50) as snippet
                    FROM bookstack_chunks_fts fts
                    JOIN bookstack_chunks bc ON fts.rowid = bc.id
                    WHERE bookstack_chunks_fts MATCH ?
                    ORDER BY rank
                    LIMIT 15
                '''

                cursor.execute(query, (fts_query,))

                for row in cursor.fetchall():
                    results.append(SearchResult(
                        doc_id=f"bookstack_chunk_{row['bookstack_id']}_{row['content_type']}_{row['chunk_index']}",
                        doc_title=row['title'],
                        doc_filename=f"BookStack {row['content_type'].title()}: {row['title']} (Chunk {row['chunk_index']})",
                        relevance_score=cls.STRATEGY_WEIGHTS.get(SearchStrategy.CHUNK_BASED, 1.3) * 0.95,  # Hohe Relevanz für Chunks
                        match_type=SearchStrategy.CHUNK_BASED,
                        snippet=row['snippet'] or f"Chunk {row['chunk_index']} aus {row['title']}",
                        metadata={
                            'source': 'bookstack_chunk',
                            'bookstack_id': row['bookstack_id'],
                            'content_type': row['content_type'],
                            'chunk_index': row['chunk_index'],
                            'word_count': row['word_count'],
                            'url': row['url']
                        }
                    ))

        except Exception as e:
            logger.error(f"Fehler bei BookStack Chunks-Suche: {str(e)}")

        return results