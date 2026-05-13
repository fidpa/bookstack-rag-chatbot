"""
Result Converters
Converts SearchResult objects to KnowledgeDocument objects
"""

import logging
from typing import List, Tuple
from utils.database import get_db_connection
from ...models import KnowledgeDocument
from .models import SearchResult

logger = logging.getLogger(__name__)


class ResultConverters:
    """Converts search results to document objects"""

    @classmethod
    def convert_to_documents(
        cls, results: List[SearchResult], page: int, per_page: int
    ) -> Tuple[List[KnowledgeDocument], int]:
        """Konvertiert SearchResults zu KnowledgeDocument Objekten (KB + BookStack)"""
        total_count = len(results)

        # Pagination
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        page_results = results[start_idx:end_idx]

        if not page_results:
            return [], total_count

        documents = []

        # Separiere KB und BookStack Results
        kb_results = []
        bookstack_results = []

        for result in page_results:
            if result.metadata and result.metadata.get("source") in [
                "bookstack",
                "bookstack_chunk",
            ]:
                bookstack_results.append(result)
            else:
                kb_results.append(result)

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()

                # Lade KB Dokumente
                if kb_results:
                    kb_doc_ids = [
                        r.doc_id for r in kb_results if isinstance(r.doc_id, int)
                    ]
                    if kb_doc_ids:
                        placeholders = ",".join("?" * len(kb_doc_ids))
                        cursor.execute(
                            f"""
                            SELECT * FROM kb_documents
                            WHERE id IN ({placeholders})
                        """,
                            kb_doc_ids,
                        )

                        doc_data = {row["id"]: dict(row) for row in cursor.fetchall()}

                        # Erstelle KB KnowledgeDocument Objekte
                        for result in kb_results:
                            if (
                                isinstance(result.doc_id, int)
                                and result.doc_id in doc_data
                            ):
                                doc = KnowledgeDocument.from_db_row(
                                    doc_data[result.doc_id]
                                )

                                # Füge Such-Metadaten hinzu
                                doc.search_snippet = result.snippet
                                doc.relevance_score = result.relevance_score
                                doc.match_type = result.match_type.value
                                doc.matched_chunks = (
                                    len(result.matched_chunks)
                                    if result.matched_chunks
                                    else 0
                                )

                                documents.append(doc)

                # Konvertiere BookStack Results zu "virtuellen" KnowledgeDocument Objekten
                for result in bookstack_results:
                    if result.metadata:
                        doc = cls._create_bookstack_document(result)
                        if doc:
                            documents.append(doc)

        except Exception as e:
            logger.error(f"Fehler beim Laden der Dokumente: {str(e)}")

        # Sortiere nach Relevanz-Score
        documents.sort(key=lambda d: getattr(d, "relevance_score", 0), reverse=True)

        return documents, total_count

    @classmethod
    def _create_bookstack_document(cls, result: SearchResult) -> "KnowledgeDocument":
        """Erstellt ein virtuelles KnowledgeDocument für BookStack Content"""
        try:
            metadata = result.metadata

            # Erstelle ein "virtuelles" KnowledgeDocument für BookStack Content
            doc = KnowledgeDocument(
                id=result.doc_id,  # String ID für BookStack
                title=result.doc_title,
                original_filename=result.doc_filename,
                filename=result.doc_filename,
                file_type="bookstack",
                file_size=0,
                uploaded_at=None,
                is_active=True,
            )

            # Füge BookStack-spezifische Metadaten hinzu
            doc.search_snippet = result.snippet
            doc.relevance_score = result.relevance_score
            doc.match_type = result.match_type.value
            doc.matched_chunks = 0

            # BookStack-spezifische Felder
            doc.bookstack_id = metadata.get("bookstack_id")
            doc.bookstack_type = metadata.get("content_type")
            doc.bookstack_url = metadata.get("url")
            doc.chunk_index = metadata.get("chunk_index")

            return doc

        except Exception as e:
            logger.error(f"Fehler beim Erstellen des BookStack-Dokuments: {str(e)}")
            return None
