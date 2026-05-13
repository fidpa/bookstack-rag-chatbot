"""
Core Hybrid Search Service
Main class coordinating the hybrid search functionality
"""

import logging
from typing import List, Dict, Tuple
from ..query_processor import QueryProcessor, QueryAnalysis, QueryIntent
from ...models import KnowledgeDocument
from .strategies import SearchStrategy
from .models import SearchResult
from .base_search import SearchImplementations
from .advanced_search import ExtendedSearchImplementations
from .fusion import ResultFusion
from .converters import ResultConverters

logger = logging.getLogger(__name__)


class HybridSearchService:
    """Service für Hybrid-Search mit Multi-Strategy Ansatz"""

    @classmethod
    def search(
        cls, query: str, page: int = 1, per_page: int = 20, active_only: bool = True
    ) -> Tuple[List[KnowledgeDocument], int, Dict]:
        """
        Führt eine Hybrid-Search durch

        Args:
            query: Suchanfrage
            page: Seiten-Nummer
            per_page: Ergebnisse pro Seite
            active_only: Nur aktive Dokumente

        Returns:
            (documents, total_count, search_info)
        """
        if not query or not query.strip():
            return [], 0, {}

        # Query analysieren
        analysis = QueryProcessor.analyze_query(query)
        logger.info(
            f"Query-Analyse: Intent={analysis.intent.value}, "
            f"Keywords={analysis.keywords}, Entities={analysis.entities}"
        )

        # Multi-Strategy Search durchführen
        all_results = cls._execute_multi_strategy_search(analysis, active_only)

        # Results fusionieren und ranken
        ranked_results = ResultFusion.fuse_and_rank_results(all_results)

        # In KnowledgeDocument Objekte konvertieren
        documents, total_count = ResultConverters.convert_to_documents(
            ranked_results, page, per_page
        )

        # Such-Info für UI/Debug
        search_info = {
            "query_analysis": analysis,
            "strategies_used": len(all_results),
            "total_raw_results": sum(len(results) for results in all_results.values()),
            "unique_documents": len(ranked_results),
        }

        return documents, total_count, search_info

    @classmethod
    def _execute_multi_strategy_search(
        cls, analysis: QueryAnalysis, active_only: bool
    ) -> Dict[SearchStrategy, List[SearchResult]]:
        """Führt verschiedene Such-Strategien aus"""
        results = {}

        # 1. Title/Tag Search
        title_results = SearchImplementations.search_title_tags(
            analysis.keywords + analysis.entities, active_only
        )
        if title_results:
            results[SearchStrategy.TITLE_TAG] = title_results

        # 2. Exact Phrase Search (wenn sinnvoll)
        if len(analysis.keywords) >= 2:
            phrase = " ".join(analysis.must_have_terms[:3])
            exact_results = SearchImplementations.search_exact_phrase(
                phrase, active_only
            )
            if exact_results:
                results[SearchStrategy.EXACT_PHRASE] = exact_results

        # 3. Keyword Search (OR)
        if analysis.keywords:
            or_results = SearchImplementations.search_keywords_or(
                analysis.keywords, active_only
            )
            if or_results:
                results[SearchStrategy.KEYWORD_OR] = or_results

        # 4. Keyword Search (AND) für must-have terms
        if len(analysis.must_have_terms) >= 2:
            and_results = ExtendedSearchImplementations.search_keywords_and(
                analysis.must_have_terms, active_only
            )
            if and_results:
                results[SearchStrategy.KEYWORD_AND] = and_results

        # 5. Proximity Search für zusammenhängende Begriffe
        if len(analysis.keywords) >= 2 and analysis.intent != QueryIntent.GENERAL:
            proximity_results = ExtendedSearchImplementations.search_proximity(
                analysis.keywords[:2], active_only, distance=10
            )
            if proximity_results:
                results[SearchStrategy.PROXIMITY] = proximity_results

        # 6. Chunk-based Search
        chunk_results = ExtendedSearchImplementations.search_chunks(
            analysis, active_only
        )
        if chunk_results:
            results[SearchStrategy.CHUNK_BASED] = chunk_results

        # 7. BookStack Content Search (NEW!)
        if analysis.keywords:
            bookstack_content_results = SearchImplementations.search_bookstack_content(
                analysis.keywords + analysis.entities, active_only
            )
            if bookstack_content_results:
                results[SearchStrategy.KEYWORD_OR] = (
                    results.get(SearchStrategy.KEYWORD_OR, [])
                    + bookstack_content_results
                )

        # 8. BookStack Chunks Search (NEW!)
        if analysis.keywords:
            bookstack_chunk_results = SearchImplementations.search_bookstack_chunks(
                analysis.keywords + analysis.entities, active_only
            )
            if bookstack_chunk_results:
                results[SearchStrategy.CHUNK_BASED] = (
                    results.get(SearchStrategy.CHUNK_BASED, [])
                    + bookstack_chunk_results
                )

        # 9. Fuzzy Search als Fallback
        if sum(len(r) for r in results.values()) < 5:  # Wenig Ergebnisse
            fuzzy_results = ExtendedSearchImplementations.search_fuzzy(
                analysis.keywords[:3], active_only
            )
            if fuzzy_results:
                results[SearchStrategy.FUZZY] = fuzzy_results

        return results
