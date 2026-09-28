"""
Search Strategy Definitions
Defines different search strategies for hybrid search
"""

from enum import Enum


class SearchStrategy(Enum):
    """The retrieval strategies whose results are fused."""

    TITLE_TAG = "title_tag"  # title, filename and tag match
    EXACT_PHRASE = "exact_phrase"  # the main terms as one phrase
    KEYWORD_OR = "keyword_or"  # any keyword
    KEYWORD_AND = "keyword_and"  # all must-have terms
    PROXIMITY = "proximity"  # two keywords within a few tokens
    FUZZY = "fuzzy"  # prefix match, fallback for few results
    CHUNK_BASED = "chunk_based"  # chunk search with the generated query variants


# Base score of a hit per strategy. A hit's score is its weight times its bm25
# relevance relative to the best hit of the same search (0..1], so the best hit
# of a strategy gets the full weight and weaker ones proportionally less.
STRATEGY_WEIGHTS = {
    SearchStrategy.TITLE_TAG: 3.0,
    SearchStrategy.EXACT_PHRASE: 2.5,
    SearchStrategy.KEYWORD_AND: 2.0,
    SearchStrategy.PROXIMITY: 1.8,
    SearchStrategy.KEYWORD_OR: 1.5,
    SearchStrategy.CHUNK_BASED: 1.3,
    SearchStrategy.FUZZY: 1.0,
}


def relative_relevance(rank: float, best_rank: float) -> float:
    """
    bm25 relevance of a hit relative to the best hit, in (0, 1].

    FTS5 reports `rank` as negative bm25: more negative is better. Both values
    are negated to get positive relevance before dividing.
    """
    best = -best_rank
    if best <= 0:
        return 1.0
    return max(-rank, 0.0) / best or 0.01
