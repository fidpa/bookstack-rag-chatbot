"""
Extended Search Implementation Functions
Contains additional search implementations for hybrid search
"""

import logging
from typing import List
from utils.database import get_db_connection
from ..query_processor import QueryProcessor, QueryAnalysis
from .strategies import SearchStrategy
from .models import SearchResult

logger = logging.getLogger(__name__)

class ExtendedSearchImplementations:
    """Extended implementation of search strategies"""
    
    STRATEGY_WEIGHTS = {
        SearchStrategy.TITLE_TAG: 3.0,
        SearchStrategy.EXACT_PHRASE: 2.5,
        SearchStrategy.KEYWORD_AND: 2.0,
        SearchStrategy.PROXIMITY: 1.8,
        SearchStrategy.KEYWORD_OR: 1.5,
        SearchStrategy.CHUNK_BASED: 1.3,
        SearchStrategy.FUZZY: 1.0
    }
    
    @classmethod
    def search_keywords_and(cls, keywords: List[str], active_only: bool) -> List[SearchResult]:
        """Sucht Dokumente die ALLE Keywords enthalten"""
        if not keywords or len(keywords) < 2:
            return []
        
        results = []
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Für AND-Suche: Prüfe ob Dokument alle Keywords enthält
                query = f'''
                    WITH keyword_matches AS (
                        SELECT 
                            c.doc_id,
                            d.title,
                            d.original_filename,
                            GROUP_CONCAT(DISTINCT LOWER(c.chunk_text)) as all_text
                        FROM kb_chunks c
                        JOIN kb_documents d ON c.doc_id = d.id
                        WHERE (? = 0 OR d.is_active = 1)
                        GROUP BY c.doc_id
                    )
                    SELECT * FROM keyword_matches
                    WHERE {' AND '.join(['all_text LIKE ?' for _ in keywords[:4]])}
                '''
                
                params = [1 if active_only else 0]
                params.extend([f'%{kw.lower()}%' for kw in keywords[:4]])
                
                cursor.execute(query, params)
                
                for row in cursor.fetchall():
                    results.append(SearchResult(
                        doc_id=row['doc_id'],
                        doc_title=row['title'] or row['original_filename'],
                        doc_filename=row['original_filename'],
                        relevance_score=cls.STRATEGY_WEIGHTS[SearchStrategy.KEYWORD_AND],
                        match_type=SearchStrategy.KEYWORD_AND,
                        snippet="Alle Suchbegriffe gefunden"
                    ))
                    
        except Exception as e:
            logger.error(f"Fehler bei Keyword AND-Suche: {str(e)}")
        
        return results
    
    @classmethod
    def search_proximity(cls, terms: List[str], active_only: bool, 
                        distance: int = 10) -> List[SearchResult]:
        """Sucht nach Begriffen in Nähe zueinander"""
        if len(terms) < 2:
            return []
        
        results = []
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # FTS5 NEAR-Query
                term1 = QueryProcessor.preprocess_for_fts5(terms[0])
                term2 = QueryProcessor.preprocess_for_fts5(terms[1])
                fts_query = f'NEAR({term1} {term2}, {distance})'
                
                query = '''
                    SELECT DISTINCT
                        c.doc_id,
                        d.title,
                        d.original_filename,
                        MIN(rank) as rank
                    FROM kb_chunks_fts fts
                    JOIN kb_chunks c ON fts.rowid = c.id
                    JOIN kb_documents d ON c.doc_id = d.id
                    WHERE kb_chunks_fts MATCH ?
                    AND (? = 0 OR d.is_active = 1)
                    GROUP BY c.doc_id, d.title, d.original_filename
                    ORDER BY rank
                    LIMIT 30
                '''
                
                cursor.execute(query, (fts_query, 1 if active_only else 0))
                
                for row in cursor.fetchall():
                    results.append(SearchResult(
                        doc_id=row['doc_id'],
                        doc_title=row['title'] or row['original_filename'],
                        doc_filename=row['original_filename'],
                        relevance_score=cls.STRATEGY_WEIGHTS[SearchStrategy.PROXIMITY],
                        match_type=SearchStrategy.PROXIMITY,
                        snippet=f"Begriffe in Nähe gefunden (Rank: {row['rank']})"
                    ))
                    
        except Exception as e:
            logger.error(f"Fehler bei Proximity-Suche: {str(e)}")
        
        return results
    
    @classmethod
    def search_chunks(cls, analysis: QueryAnalysis, active_only: bool) -> List[SearchResult]:
        """Haupt-Chunk-basierte Suche"""
        results = []
        
        # Verwende die generierten Such-Queries
        for search_query in analysis.search_queries[:3]:  # Top 3 queries
            try:
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    
                    fts_query = QueryProcessor.preprocess_for_fts5(search_query)
                    
                    query = '''
                        SELECT
                            c.doc_id,
                            c.chunk_index,
                            c.chunk_text,
                            d.title,
                            d.original_filename,
                            snippet(kb_chunks_fts, 0, '<mark>', '</mark>', '...', 50) as snippet,
                            rank,
                            c.word_count
                        FROM kb_chunks_fts fts
                        JOIN kb_chunks c ON fts.rowid = c.id
                        JOIN kb_documents d ON c.doc_id = d.id
                        WHERE kb_chunks_fts MATCH ?
                        AND (? = 0 OR d.is_active = 1)
                        ORDER BY rank
                        LIMIT 100
                    '''
                    
                    cursor.execute(query, (fts_query, 1 if active_only else 0))
                    
                    # Gruppiere nach Dokument und berechne Relevanz
                    doc_results = {}
                    for row in cursor.fetchall():
                        doc_id = row['doc_id']
                        
                        if doc_id not in doc_results:
                            doc_results[doc_id] = {
                                'result': SearchResult(
                                    doc_id=doc_id,
                                    doc_title=row['title'] or row['original_filename'],
                                    doc_filename=row['original_filename'],
                                    relevance_score=0,  # Wird berechnet
                                    match_type=SearchStrategy.CHUNK_BASED,
                                    snippet=row['snippet']
                                ),
                                'total_rank': 0,
                                'chunk_count': 0
                            }
                        
                        doc_results[doc_id]['result'].matched_chunks.append({
                            'chunk_index': row['chunk_index'],
                            'snippet': row['snippet'],
                            'rank': row['rank'],
                            'word_count': row['word_count']
                        })
                        doc_results[doc_id]['total_rank'] += abs(row['rank'])
                        doc_results[doc_id]['chunk_count'] += 1
                    
                    # Berechne finale Scores
                    for doc_data in doc_results.values():
                        # Score basiert auf durchschnittlichem Rank und Anzahl Matches
                        avg_rank = doc_data['total_rank'] / doc_data['chunk_count']
                        match_boost = min(doc_data['chunk_count'] / 5, 2)  # Boost für viele Matches
                        
                        base_score = cls.STRATEGY_WEIGHTS[SearchStrategy.CHUNK_BASED]
                        doc_data['result'].relevance_score = base_score * match_boost * (1 / (1 + avg_rank))
                        
                        results.append(doc_data['result'])
                        
            except Exception as e:
                # Truncate query for logging to avoid cut-off errors
                log_query = search_query[:50] + '...' if len(search_query) > 50 else search_query
                logger.error(f"Fehler bei Chunk-Suche für Query '{log_query}': {str(e)}")
        
        return results
    
    @classmethod
    def search_fuzzy(cls, terms: List[str], active_only: bool) -> List[SearchResult]:
        """Fuzzy/Prefix-Suche als Fallback"""
        if not terms:
            return []
        
        results = []
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Erstelle Prefix-Queries
                fuzzy_terms = []
                for term in terms:
                    if len(term) >= 4:  # Nur für längere Begriffe
                        fuzzy_terms.append(f'{QueryProcessor.preprocess_for_fts5(term)}*')
                
                if not fuzzy_terms:
                    return []
                
                fts_query = ' OR '.join(fuzzy_terms)
                
                query = '''
                    SELECT DISTINCT
                        c.doc_id,
                        d.title,
                        d.original_filename,
                        snippet(kb_chunks_fts, 0, '<mark>', '</mark>', '...', 30) as snippet
                    FROM kb_chunks_fts fts
                    JOIN kb_chunks c ON fts.rowid = c.id
                    JOIN kb_documents d ON c.doc_id = d.id
                    WHERE kb_chunks_fts MATCH ?
                    AND (? = 0 OR d.is_active = 1)
                    LIMIT 20
                '''
                
                cursor.execute(query, (fts_query, 1 if active_only else 0))
                
                for row in cursor.fetchall():
                    results.append(SearchResult(
                        doc_id=row['doc_id'],
                        doc_title=row['title'] or row['original_filename'],
                        doc_filename=row['original_filename'],
                        relevance_score=cls.STRATEGY_WEIGHTS[SearchStrategy.FUZZY],
                        match_type=SearchStrategy.FUZZY,
                        snippet=row['snippet']
                    ))
                    
        except Exception as e:
            logger.error(f"Fehler bei Fuzzy-Suche: {str(e)}")
        
        return results