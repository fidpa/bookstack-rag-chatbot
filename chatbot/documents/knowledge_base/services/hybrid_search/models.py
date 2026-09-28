"""
Search Models
Data classes for search results
"""

from dataclasses import dataclass, field
from typing import Dict, List, Union
from .strategies import SearchStrategy


@dataclass
class SearchResult:
    """One search hit: an uploaded document (int id) or a BookStack item
    (str id, see base_search.bookstack_doc_id)."""

    doc_id: Union[int, str]
    doc_title: str
    doc_filename: str
    relevance_score: float
    match_type: SearchStrategy
    matched_chunks: List[Dict] = field(default_factory=list)
    snippet: str = ""
    metadata: Dict = field(default_factory=dict)  # BookStack source, id, type, url

    def __hash__(self):
        return hash(self.doc_id)
