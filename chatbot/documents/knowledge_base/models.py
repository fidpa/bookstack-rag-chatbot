"""
Data model of the knowledge base
"""

from datetime import datetime
from typing import Dict, List, Optional, Union
from dataclasses import dataclass, field


@dataclass
class KnowledgeDocument:
    """An uploaded document, or a BookStack hit dressed as one by the search."""

    # int for uploaded documents; str for the virtual documents the search
    # builds for BookStack hits (see hybrid_search.converters)
    id: Optional[Union[int, str]] = None
    filename: str = ""
    original_filename: str = ""
    file_path: str = ""
    file_size: int = 0
    file_type: str = ""
    title: Optional[str] = None
    description: Optional[str] = None
    content_hash: str = ""
    uploaded_by: str = "system"
    uploaded_at: Optional[datetime] = None
    last_indexed: Optional[datetime] = None
    is_active: bool = True

    # Set by the hybrid search on hits
    search_snippet: str = ""
    relevance_score: float = 0.0
    match_type: str = ""
    matched_chunks: int = 0
    # Set on BookStack hits only
    bookstack_id: Optional[int] = None
    bookstack_type: Optional[str] = None
    bookstack_url: Optional[str] = None
    bookstack_chunks: List[str] = field(default_factory=list)

    @staticmethod
    def from_db_row(row: Dict) -> "KnowledgeDocument":
        """Build from a kb_documents row."""
        return KnowledgeDocument(
            id=row["id"],
            filename=row["filename"],
            original_filename=row["original_filename"],
            file_path=row["file_path"],
            file_size=row["file_size"],
            file_type=row["file_type"],
            title=row["title"],
            description=row["description"],
            content_hash=row["content_hash"],
            uploaded_by=row["uploaded_by"],
            uploaded_at=(
                datetime.fromisoformat(row["uploaded_at"])
                if row["uploaded_at"]
                else None
            ),
            last_indexed=(
                datetime.fromisoformat(row["last_indexed"])
                if row["last_indexed"]
                else None
            ),
            is_active=bool(row["is_active"]),
        )
