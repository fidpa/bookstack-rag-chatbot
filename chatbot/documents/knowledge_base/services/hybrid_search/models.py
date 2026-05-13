"""
Search Models
Data classes for search results
"""

from dataclasses import dataclass, field
from typing import List, Dict
from .strategies import SearchStrategy


@dataclass
class SearchResult:
    """Einzelnes Suchergebnis"""

    doc_id: int
    doc_title: str
    doc_filename: str
    relevance_score: float
    match_type: SearchStrategy
    matched_chunks: List[Dict] = field(default_factory=list)
    snippet: str = ""
    metadata: Dict = field(default_factory=dict)  # NEW: For BookStack metadata

    def __hash__(self):
        return hash(self.doc_id)
