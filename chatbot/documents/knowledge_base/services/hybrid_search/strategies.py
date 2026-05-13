"""
Search Strategy Definitions
Defines different search strategies for hybrid search
"""

from enum import Enum


class SearchStrategy(Enum):
    """Verschiedene Such-Strategien"""

    TITLE_TAG = "title_tag"  # Suche in Titel und Tags
    EXACT_PHRASE = "exact_phrase"  # Exakte Phrasensuche
    KEYWORD_OR = "keyword_or"  # Keywords mit OR
    KEYWORD_AND = "keyword_and"  # Keywords mit AND
    PROXIMITY = "proximity"  # NEAR-Operator
    FUZZY = "fuzzy"  # Prefix/Wildcard-Suche
    CHUNK_BASED = "chunk_based"  # Chunk-basierte Suche
