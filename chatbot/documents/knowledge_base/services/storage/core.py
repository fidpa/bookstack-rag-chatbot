"""
Core Storage Service für Knowledge Base
Hauptklasse für die Storage-Verwaltung
"""

import os
import logging
from typing import Optional, Tuple, Dict, List
from werkzeug.datastructures import FileStorage

from ...models import KnowledgeDocument
from . import file_operations, metadata, statistics

logger = logging.getLogger(__name__)

class StorageService:
    """Service für die permanente Speicherung von Wissensbasis-Dokumenten"""
    
    # Storage configuration
    STORAGE_BASE_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))), 
        'data', 'knowledge_base'
    )
    
    @classmethod
    def ensure_storage_directory(cls) -> None:
        """Stellt sicher, dass das Storage-Verzeichnis existiert"""
        os.makedirs(cls.STORAGE_BASE_PATH, exist_ok=True)
    
    # Delegate to file_operations module
    @classmethod
    def calculate_file_hash(cls, file_content: bytes) -> str:
        """Berechnet den SHA256 Hash einer Datei"""
        return file_operations.calculate_file_hash(file_content)
    
    @classmethod
    def check_duplicate(cls, content_hash: str) -> Optional[KnowledgeDocument]:
        """Prüft ob ein Dokument mit diesem Hash bereits existiert"""
        return file_operations.check_duplicate(content_hash)
    
    @classmethod
    def save_file(cls, file: FileStorage, title: str = "", description: str = "", tags: list = None) -> Tuple[bool, str, Optional[KnowledgeDocument]]:
        """Speichert eine Datei permanent in der Wissensbasis"""
        return file_operations.save_file(file, title, description, tags)
    
    @classmethod
    def delete_file(cls, doc_id: int) -> Tuple[bool, str]:
        """Löscht ein Dokument aus der Wissensbasis"""
        return file_operations.delete_file(doc_id)
    
    @classmethod
    def get_document_by_id(cls, doc_id: int) -> Optional[KnowledgeDocument]:
        """Lädt ein Dokument anhand seiner ID"""
        return file_operations.get_document_by_id(doc_id)
    
    # Delegate to metadata module
    @classmethod
    def get_document_tags(cls, doc_id: int) -> List[str]:
        """Lädt alle Tags eines Dokuments"""
        return metadata.get_document_tags(doc_id)
    
    @classmethod
    def update_metadata(cls, doc_id: int, title: str, description: str, tags: List[str]) -> Tuple[bool, str]:
        """Aktualisiert die Metadaten eines Dokuments"""
        return metadata.update_metadata(doc_id, title, description, tags)
    
    @classmethod
    def _extract_markdown_metadata(cls, file_path: str) -> Optional[Dict]:
        """Extrahiert Metadaten aus Markdown-Frontmatter"""
        return metadata._extract_markdown_metadata(file_path)
    
    # Delegate to statistics module
    @classmethod
    def get_chunk_stats(cls, doc_id: int) -> Dict:
        """Holt Chunk-Statistiken für ein Dokument"""
        return statistics.get_chunk_stats(doc_id)