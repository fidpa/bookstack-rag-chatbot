"""
Metadata Operations für Storage Service
Verwaltet Metadaten-Operationen wie Tags und Markdown-Frontmatter
"""

import logging
from typing import Dict, List, Optional, Tuple
import yaml
import re

from utils.database import get_db_connection

logger = logging.getLogger(__name__)


def get_document_tags(doc_id: int) -> List[str]:
    """
    Lädt alle Tags eines Dokuments

    Returns:
        Liste von Tag-Strings
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT tag FROM kb_tags 
                WHERE document_id = ? 
                ORDER BY tag
            """,
                (doc_id,),
            )

            return [row["tag"] for row in cursor.fetchall()]

    except Exception as e:
        logger.error(f"Fehler beim Laden der Tags für Dokument {doc_id}: {str(e)}")
        return []


def update_metadata(
    doc_id: int, title: str, description: str, tags: List[str]
) -> Tuple[bool, str]:
    """
    Aktualisiert die Metadaten eines Dokuments

    Returns:
        (success, message)
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Prüfe ob Dokument existiert
            cursor.execute("SELECT id FROM kb_documents WHERE id = ?", (doc_id,))
            if not cursor.fetchone():
                return False, "Dokument nicht gefunden"

            # Update Dokument-Metadaten
            cursor.execute(
                """
                UPDATE kb_documents 
                SET title = ?, description = ?
                WHERE id = ?
            """,
                (title, description, doc_id),
            )

            # Tags aktualisieren - erst alle löschen
            cursor.execute("DELETE FROM kb_tags WHERE document_id = ?", (doc_id,))

            # Neue Tags einfügen
            for tag in tags:
                tag = tag.strip()
                if tag:  # Nur nicht-leere Tags
                    cursor.execute(
                        """
                        INSERT INTO kb_tags (document_id, tag)
                        VALUES (?, ?)
                    """,
                        (doc_id, tag),
                    )

            conn.commit()

            logger.info(f"Metadaten für Dokument {doc_id} erfolgreich aktualisiert")
            return True, "Metadaten erfolgreich aktualisiert"

    except Exception as e:
        logger.error(
            f"Fehler beim Aktualisieren der Metadaten für Dokument {doc_id}: {str(e)}"
        )
        return False, f"Fehler beim Aktualisieren: {str(e)}"


def _extract_markdown_metadata(file_path: str) -> Optional[Dict]:
    """
    Extrahiert Metadaten aus Markdown-Frontmatter

    Returns:
        Dict mit extrahierten Metadaten oder None
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check for frontmatter
        if not content.startswith("---"):
            return None

        # Extract frontmatter
        frontmatter_match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
        if not frontmatter_match:
            return None

        frontmatter_yaml = frontmatter_match.group(1)

        # Parse YAML
        try:
            metadata = yaml.safe_load(frontmatter_yaml)
            if not isinstance(metadata, dict):
                return None

            # Extract relevant fields
            result = {}

            # Title
            if "title" in metadata:
                result["title"] = str(metadata["title"])
            elif "titel" in metadata:  # German variant
                result["title"] = str(metadata["titel"])

            # Description
            if "description" in metadata:
                result["description"] = str(metadata["description"])
            elif "beschreibung" in metadata:  # German variant
                result["description"] = str(metadata["beschreibung"])
            elif "summary" in metadata:
                result["description"] = str(metadata["summary"])

            # Tags
            tags = []
            if "tags" in metadata:
                if isinstance(metadata["tags"], list):
                    tags = [str(tag) for tag in metadata["tags"]]
                elif isinstance(metadata["tags"], str):
                    tags = [tag.strip() for tag in metadata["tags"].split(",")]
            elif "keywords" in metadata:
                if isinstance(metadata["keywords"], list):
                    tags = [str(kw) for kw in metadata["keywords"]]
                elif isinstance(metadata["keywords"], str):
                    tags = [kw.strip() for kw in metadata["keywords"].split(",")]

            if tags:
                result["tags"] = tags

            # Additional metadata that might be useful
            if "author" in metadata or "autor" in metadata:
                author = metadata.get("author", metadata.get("autor"))
                if author and "description" in result:
                    result["description"] += f" (Autor: {author})"
                elif author:
                    result["description"] = f"Autor: {author}"

            return result if result else None

        except yaml.YAMLError as e:
            logger.warning(f"Failed to parse YAML frontmatter: {str(e)}")
            return None

    except Exception as e:
        logger.error(f"Error extracting markdown metadata: {str(e)}")
        return None
