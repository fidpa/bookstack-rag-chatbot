"""
Result Fusion and Ranking
Handles the fusion and ranking of search results from multiple strategies
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Set, Union

from .strategies import SearchStrategy
from .models import SearchResult

logger = logging.getLogger(__name__)

# Score multiplier per distinct strategy that found a document
STRATEGY_BONUS = 0.5


@dataclass
class _Fused:
    result: SearchResult
    total_score: float = 0.0
    strategies: Set[SearchStrategy] = field(default_factory=set)


class ResultFusion:
    """Handles fusion and ranking of search results"""

    @classmethod
    def fuse_and_rank_results(
        cls, all_results: Dict[SearchStrategy, List[SearchResult]]
    ) -> List[SearchResult]:
        """
        Merge the per-strategy hit lists into one ranking.

        A document's score is the sum of its hit scores, multiplied by
        1 + 0.5 per distinct strategy that found it. The first hit seen for a
        document is kept as its result; later hits contribute their matched
        chunks and, if longer, their snippet.
        """
        fused: Dict[Union[int, str], _Fused] = {}

        for strategy, results in all_results.items():
            for result in results:
                entry = fused.setdefault(result.doc_id, _Fused(result=result))
                entry.total_score += result.relevance_score
                entry.strategies.add(strategy)

                if entry.result is result:
                    continue
                if result.snippet and len(result.snippet) > len(entry.result.snippet):
                    entry.result.snippet = result.snippet
                entry.result.matched_chunks.extend(result.matched_chunks)
                entry.result.metadata = {**result.metadata, **entry.result.metadata}

        # Each strategy counts once: the BookStack searches add to the KEYWORD_OR
        # and CHUNK_BASED lists, and a repeat there says nothing about agreement
        # between methods.
        for entry in fused.values():
            entry.total_score *= 1 + len(entry.strategies) * STRATEGY_BONUS
            entry.result.relevance_score = entry.total_score

        ranked = sorted(fused.values(), key=lambda e: e.total_score, reverse=True)
        return [entry.result for entry in ranked]
