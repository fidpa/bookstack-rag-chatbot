"""
Extended Search Implementation Functions
Contains additional search implementations for hybrid search
"""

import logging
from typing import Dict, List, Union

from ..query_processor import QueryAnalysis
from ..query_processor.preprocessor import (
    match_all,
    match_near,
    match_prefix,
    QueryPreprocessor,
)
from .base_search import SearchImplementations
from .strategies import SearchStrategy, STRATEGY_WEIGHTS
from .models import SearchResult

logger = logging.getLogger(__name__)


class ExtendedSearchImplementations:
    """Extended implementation of search strategies"""

    STRATEGY_WEIGHTS = STRATEGY_WEIGHTS

    @classmethod
    def search_keywords_and(
        cls, keywords: List[str], active_only: bool
    ) -> List[SearchResult]:
        """Chunks containing all of the keywords (up to four)."""
        if len(keywords) < 2:
            return []
        try:
            return SearchImplementations._kb_chunk_hits(
                match_all(keywords[:4]), active_only, SearchStrategy.KEYWORD_AND, 50
            )
        except Exception as e:
            logger.error(f"Keyword AND search failed: {e}")
            return []

    @classmethod
    def search_proximity(
        cls, terms: List[str], active_only: bool, distance: int = 10
    ) -> List[SearchResult]:
        """Chunks where the first two terms occur within `distance` tokens."""
        if len(terms) < 2:
            return []
        try:
            return SearchImplementations._kb_chunk_hits(
                match_near(terms[0], terms[1], distance),
                active_only,
                SearchStrategy.PROXIMITY,
                30,
            )
        except Exception as e:
            logger.error(f"Proximity search failed: {e}")
            return []

    @classmethod
    def search_chunks(
        cls, analysis: QueryAnalysis, active_only: bool
    ) -> List[SearchResult]:
        """
        Chunk search over the generated query variants.

        Each variant is searched separately; a document found by several keeps
        its best score and the union of its matched chunks, so it enters the
        fusion once.
        """
        merged: Dict[Union[int, str], SearchResult] = {}

        for search_query in analysis.search_queries[:3]:
            try:
                hits = SearchImplementations._kb_chunk_hits(
                    QueryPreprocessor.preprocess_for_fts5(search_query),
                    active_only,
                    SearchStrategy.CHUNK_BASED,
                )
            except Exception as e:
                logger.error(f"Chunk search failed for '{search_query[:50]}': {e}")
                continue

            for hit in hits:
                # More matching chunks: up to twice the score
                hit.relevance_score *= 1 + min(len(hit.matched_chunks) / 5, 1)
                known = merged.get(hit.doc_id)
                if known is None:
                    merged[hit.doc_id] = hit
                    continue
                known.relevance_score = max(known.relevance_score, hit.relevance_score)
                seen = {c["chunk_index"] for c in known.matched_chunks}
                known.matched_chunks.extend(
                    c for c in hit.matched_chunks if c["chunk_index"] not in seen
                )

        return list(merged.values())

    @classmethod
    def search_fuzzy(cls, terms: List[str], active_only: bool) -> List[SearchResult]:
        """Prefix search on terms of four or more characters, as a fallback."""
        try:
            return SearchImplementations._kb_chunk_hits(
                match_prefix(t for t in terms if len(t) >= 4),
                active_only,
                SearchStrategy.FUZZY,
                20,
            )
        except Exception as e:
            logger.error(f"Fuzzy search failed: {e}")
            return []
