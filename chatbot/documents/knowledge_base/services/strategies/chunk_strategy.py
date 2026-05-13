"""
Chunk-based context building strategy
"""

import logging
from typing import List

from utils.database import get_db_connection
from ...models import KnowledgeDocument

logger = logging.getLogger(__name__)


class ChunkSelectionStrategy:
    """Strategy for building chunk-based context from knowledge base"""

    @classmethod
    def build_context(
        cls, documents: List[KnowledgeDocument], query: str, max_tokens: int = 3000
    ) -> str:
        """
        Erstellt einen Chunk-basierten Kontext aus den gefundenen Dokumenten

        Args:
            documents: Liste von gefundenen Dokumenten
            query: Original-Query des Nutzers
            max_tokens: Maximale Token für Kontext

        Returns:
            Formatierter Chunk-basierter Kontext
        """
        try:
            context_parts = []
            context_parts.append("## Relevante Informationen aus der Wissensbasis:\n")

            total_tokens = 0

            # Sammle relevante Chunks von allen Dokumenten
            all_chunks = []

            with get_db_connection() as conn:
                cursor = conn.cursor()

                for doc in documents:
                    # Preprocess query for FTS5
                    from ...services.query_processor import QueryProcessor

                    fts_query = QueryProcessor.preprocess_for_fts5(query)

                    # Hole die relevantesten Chunks für dieses Dokument
                    cursor.execute(
                        """
                        SELECT
                            c.chunk_text,
                            c.chunk_index,
                            snippet(kb_chunks_fts, 0, '<mark>', '</mark>', '...', 50) as snippet,
                            rank
                        FROM kb_chunks_fts fts
                        JOIN kb_chunks c ON fts.rowid = c.id
                        WHERE c.doc_id = ?
                        AND kb_chunks_fts MATCH ?
                        ORDER BY rank
                        LIMIT 5
                    """,
                        (doc.id, fts_query),
                    )

                    doc_chunks = cursor.fetchall()

                    for chunk_row in doc_chunks:
                        all_chunks.append(
                            {
                                "doc_title": doc.title or doc.original_filename,
                                "doc_id": doc.id,
                                "chunk_text": chunk_row["chunk_text"],
                                "chunk_index": chunk_row["chunk_index"],
                                "snippet": chunk_row["snippet"],
                                "rank": abs(chunk_row["rank"]),
                            }
                        )

            # Sortiere alle Chunks nach Relevanz
            all_chunks.sort(key=lambda x: x["rank"])

            # Gruppiere nach Dokument für bessere Struktur
            doc_chunks_map = {}
            for chunk in all_chunks:
                doc_id = chunk["doc_id"]
                if doc_id not in doc_chunks_map:
                    doc_chunks_map[doc_id] = {"title": chunk["doc_title"], "chunks": []}
                doc_chunks_map[doc_id]["chunks"].append(chunk)

            # Baue Kontext auf
            for doc_idx, (doc_id, doc_data) in enumerate(doc_chunks_map.items(), 1):
                # Dokument-Header
                context_parts.append(f"\n### Dokument {doc_idx}: {doc_data['title']}")

                # Top Chunks dieses Dokuments
                for chunk_idx, chunk in enumerate(
                    doc_data["chunks"][:3], 1
                ):  # Max 3 Chunks pro Dokument
                    chunk_text = chunk["chunk_text"]

                    # Token-Limit prüfen
                    chunk_tokens = len(chunk_text.split())
                    if total_tokens + chunk_tokens > max_tokens:
                        # Kürze den letzten Chunk wenn nötig
                        remaining_tokens = max_tokens - total_tokens
                        if remaining_tokens > 50:
                            words = chunk_text.split()[:remaining_tokens]
                            chunk_text = " ".join(words) + "..."
                            context_parts.append(
                                f"\n[Auszug {chunk_idx}]\n{chunk_text}"
                            )

                        # Context-Limit erreicht
                        context_parts.append(
                            "\n\n[Weitere relevante Informationen vorhanden, aber Context-Limit erreicht]"
                        )
                        return "\n".join(context_parts)

                    context_parts.append(f"\n[Auszug {chunk_idx}]\n{chunk_text}")
                    total_tokens += chunk_tokens

            full_context = "\n".join(context_parts)
            logger.info(
                f"Chunk-basierter Kontext erstellt: {len(doc_chunks_map)} Dokumente, {len(all_chunks)} Chunks, {total_tokens} Tokens"
            )

            return full_context

        except Exception as e:
            logger.error(
                f"Fehler beim Erstellen des Chunk-basierten Kontexts: {str(e)}",
                exc_info=True,
            )
            # Fallback zu einfachem Kontext
            return cls._format_simple_context(documents)

    @classmethod
    def _format_simple_context(cls, documents: List[KnowledgeDocument]) -> str:
        """Einfacher Fallback-Kontext ohne Chunks"""
        context_parts = ["## Relevante Informationen aus der Wissensbasis:\n"]

        for idx, doc in enumerate(documents[:3], 1):  # Max 3 Dokumente
            title = doc.title or doc.original_filename
            snippet = getattr(doc, "search_snippet", "") or "Dokument gefunden"

            context_parts.append(f"\n### Dokument {idx}: {title}")
            context_parts.append(
                snippet[:500] + "..." if len(snippet) > 500 else snippet
            )

        return "\n".join(context_parts)
