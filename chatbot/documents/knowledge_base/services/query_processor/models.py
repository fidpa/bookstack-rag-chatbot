"""
Query Processor Models
Data classes and enums for query processing
"""

from dataclasses import dataclass
from enum import Enum
from typing import List


class QueryIntent(Enum):
    """Typen von Such-Intents"""

    DEFINITION = "definition"  # Was ist X?
    COMPARISON = "comparison"  # X vs Y
    EXPLANATION = "explanation"  # Wie funktioniert X?
    EXAMPLE = "example"  # Beispiel für X
    LIST = "list"  # Liste von X
    SPECIFIC = "specific"  # Spezifische Information
    GENERAL = "general"  # Allgemeine Suche


@dataclass
class QueryAnalysis:
    """Ergebnis der Query-Analyse"""

    original_query: str
    cleaned_query: str
    keywords: List[str]
    entities: List[str]
    intent: QueryIntent
    search_queries: List[str]
    must_have_terms: List[str]  # Begriffe die unbedingt vorkommen müssen
    nice_to_have_terms: List[str]  # Optionale Begriffe
