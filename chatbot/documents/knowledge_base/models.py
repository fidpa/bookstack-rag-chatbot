"""
Datenbank-Modelle für die Wissensbasis
"""

from datetime import datetime
from typing import Optional, Dict
from dataclasses import dataclass
import hashlib


@dataclass
class KnowledgeDocument:
    """Model für ein Wissensbasis-Dokument"""

    id: Optional[int] = None
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

    @staticmethod
    def from_db_row(row: Dict) -> "KnowledgeDocument":
        """Erstellt ein KnowledgeDocument aus einer Datenbankzeile"""
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

    def calculate_hash(self, file_content: bytes) -> str:
        """Berechnet den SHA256 Hash des Dateiinhalts"""
        return hashlib.sha256(file_content).hexdigest()

    def get_display_size(self) -> str:
        """Gibt die Dateigröße in lesbarem Format zurück"""
        size = self.file_size
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} TB"


@dataclass
class KnowledgeTag:
    """Model für Tags/Keywords eines Dokuments"""

    id: Optional[int] = None
    document_id: int = 0
    tag: str = ""
