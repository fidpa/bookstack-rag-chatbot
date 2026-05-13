"""
Search Service für Knowledge Base
Implementiert die Volltext-Suche in der Wissensbasis
"""

import logging
from typing import List, Optional, Tuple

from utils.database import get_db_connection
from ..models import KnowledgeDocument
from .hybrid_search import HybridSearchService

logger = logging.getLogger(__name__)


class SearchService:
    """Service für die Suche in der Wissensbasis"""

    @classmethod
    def search_documents(
        cls,
        query: str,
        page: int = 1,
        per_page: int = 20,
        active_only: bool = True,
        use_hybrid: bool = True,
    ):
        """
        Führt eine Volltext-Suche in der Wissensbasis durch mit Pagination

        Args:
            query: Suchbegriff(e)
            page: Seiten-Nummer (1-basiert)
            per_page: Ergebnisse pro Seite
            active_only: Nur aktive Dokumente suchen
            use_hybrid: Ob die neue Hybrid-Search verwendet werden soll

        Returns:
            Bei use_hybrid=True: (documents, total_count, search_info)
            Bei use_hybrid=False: (documents, total_count)
        """
        if not query or not query.strip():
            if use_hybrid:
                return [], 0, {}
            return [], 0

        # Verwende Hybrid-Search wenn aktiviert
        if use_hybrid:
            try:
                documents, total_count, search_info = HybridSearchService.search(
                    query=query, page=page, per_page=per_page, active_only=active_only
                )

                # Logge Such-Info
                logger.info(
                    f"Hybrid-Search für '{query}': {search_info.get('unique_documents', 0)} eindeutige Dokumente gefunden"
                )

                return documents, total_count, search_info
            except Exception as e:
                logger.error(
                    f"Fehler bei Hybrid-Search, falle zurück auf Legacy: {str(e)}"
                )
                # Fallback zu Legacy-Suche

        # Escape special characters for FTS5
        # FTS5 special characters: " * ( ) : ^ -
        escaped_query = query
        for char in ['"', "*", "(", ")", ":", "^", "-"]:
            escaped_query = escaped_query.replace(char, f"\\{char}")
        # Remove ? as it's not supported in FTS5
        escaped_query = escaped_query.replace("?", "")

        documents = []
        total_count = 0

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()

                # Zuerst Total Count ermitteln
                cursor.execute(
                    """
                    SELECT COUNT(*) as count
                    FROM kb_search_fts s
                    JOIN kb_documents d ON s.doc_id = d.id
                    WHERE kb_search_fts MATCH ?
                    AND (? = 0 OR d.is_active = 1)
                """,
                    (escaped_query, 1 if active_only else 0),
                )

                total_count = cursor.fetchone()["count"]

                # Dann paginierte Ergebnisse holen
                offset = (page - 1) * per_page
                cursor.execute(
                    """
                    SELECT 
                        d.*,
                        snippet(knowledge_search, 2, '<mark>', '</mark>', '...', 50) as snippet,
                        rank
                    FROM kb_search_fts s
                    JOIN kb_documents d ON s.doc_id = d.id
                    WHERE kb_search_fts MATCH ?
                    AND (? = 0 OR d.is_active = 1)
                    ORDER BY rank
                    LIMIT ? OFFSET ?
                """,
                    (escaped_query, 1 if active_only else 0, per_page, offset),
                )

                for row in cursor.fetchall():
                    doc = KnowledgeDocument.from_db_row(dict(row))
                    # Füge das Snippet als zusätzliches Attribut hinzu
                    doc.search_snippet = row["snippet"]
                    documents.append(doc)

                logger.info(
                    f"Suche nach '{query}' (escaped: '{escaped_query}') ergab {total_count} Treffer (Seite {page})"
                )

        except Exception as e:
            logger.error(f"Fehler bei der Suche: {str(e)}")

        # Legacy-Suche gibt keine search_info zurück
        return documents, total_count

    @classmethod
    def get_all_documents(
        cls, page: int = 1, per_page: int = 20, only_active: Optional[bool] = None
    ) -> Tuple[List[KnowledgeDocument], int]:
        """
        Holt alle Dokumente mit Pagination

        Args:
            page: Seiten-Nummer (1-basiert)
            per_page: Dokumente pro Seite
            only_active: None = alle, True = nur aktive, False = nur inaktive

        Returns:
            (documents, total_count)
        """
        documents = []
        total_count = 0

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()

                # Basis-Query
                where_clause = ""
                params = []

                if only_active is not None:
                    where_clause = "WHERE is_active = ?"
                    params.append(1 if only_active else 0)

                # Total count
                cursor.execute(
                    f"""
                    SELECT COUNT(*) as count 
                    FROM kb_documents 
                    {where_clause}
                """,
                    params,
                )
                total_count = cursor.fetchone()["count"]

                # Dokumente mit Pagination
                offset = (page - 1) * per_page
                cursor.execute(
                    f"""
                    SELECT * FROM kb_documents 
                    {where_clause}
                    ORDER BY uploaded_at DESC
                    LIMIT ? OFFSET ?
                """,
                    params + [per_page, offset],
                )

                for row in cursor.fetchall():
                    documents.append(KnowledgeDocument.from_db_row(dict(row)))

        except Exception as e:
            logger.error(f"Fehler beim Abrufen der Dokumente: {str(e)}")

        return documents, total_count

    @classmethod
    def get_document_by_id(cls, doc_id: int) -> Optional[KnowledgeDocument]:
        """Holt ein einzelnes Dokument anhand der ID"""
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM kb_documents WHERE id = ?", (doc_id,))
                row = cursor.fetchone()

                if row:
                    return KnowledgeDocument.from_db_row(dict(row))

        except Exception as e:
            logger.error(f"Fehler beim Abrufen von Dokument {doc_id}: {str(e)}")

        return None

    @classmethod
    def toggle_document_status(cls, doc_id: int) -> Tuple[bool, str]:
        """
        Aktiviert/Deaktiviert ein Dokument

        Returns:
            (success, message)
        """
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()

                # Aktuellen Status abfragen
                cursor.execute(
                    "SELECT is_active FROM kb_documents WHERE id = ?", (doc_id,)
                )
                row = cursor.fetchone()

                if not row:
                    return False, "Dokument nicht gefunden"

                # Status umschalten
                new_status = not bool(row["is_active"])
                cursor.execute(
                    """
                    UPDATE kb_documents 
                    SET is_active = ? 
                    WHERE id = ?
                """,
                    (new_status, doc_id),
                )

                conn.commit()

                status_text = "aktiviert" if new_status else "deaktiviert"
                logger.info(f"Dokument {doc_id} wurde {status_text}")

                return True, f"Dokument erfolgreich {status_text}"

        except Exception as e:
            logger.error(f"Fehler beim Ändern des Dokument-Status {doc_id}: {str(e)}")
            return False, f"Status-Änderung fehlgeschlagen: {str(e)}"

    @classmethod
    def search_by_tags(cls, tags: List[str]) -> List[KnowledgeDocument]:
        """Sucht Dokumente anhand von Tags"""
        documents = []

        if not tags:
            return documents

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()

                # Placeholder für SQL IN clause
                placeholders = ",".join("?" * len(tags))

                cursor.execute(
                    f"""
                    SELECT DISTINCT d.* 
                    FROM kb_documents d
                    JOIN kb_tags t ON d.id = t.document_id
                    WHERE t.tag IN ({placeholders})
                    AND d.is_active = 1
                    ORDER BY d.uploaded_at DESC
                """,
                    tags,
                )

                for row in cursor.fetchall():
                    documents.append(KnowledgeDocument.from_db_row(dict(row)))

        except Exception as e:
            logger.error(f"Fehler bei Tag-Suche: {str(e)}")

        return documents
