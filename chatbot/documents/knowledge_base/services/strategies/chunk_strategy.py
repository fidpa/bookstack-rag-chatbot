"""
Chunk-based context building strategy
"""

import logging
import re
from typing import List, Tuple

from utils.database import get_db_connection
from ...models import KnowledgeDocument
from ..query_processor import QueryProcessor

logger = logging.getLogger(__name__)

#: FTS5 snippet() can wrap matched terms in these; they are noise in an LLM prompt.
_SNIPPET_MARKS = re.compile(r"</?mark>")

#: Excerpts taken per document
CHUNKS_PER_DOCUMENT = 3


def _clean_snippet(snippet: str) -> str:
    """Strip <mark> tags from a snippet."""
    return _SNIPPET_MARKS.sub("", snippet or "").strip()


def _is_bookstack_document(doc: KnowledgeDocument) -> bool:
    """True for the virtual documents ResultConverters builds for wiki hits.

    They carry a string id such as ``bookstack_12_page`` and have no row in
    kb_documents, so the kb_chunks lookup below cannot find anything for them.
    """
    return getattr(doc, "file_type", None) == "bookstack"


class ChunkSelectionStrategy:
    """Strategy for building chunk-based context from knowledge base"""

    @classmethod
    def build_context(
        cls, documents: List[KnowledgeDocument], query: str, max_tokens: int = 3000
    ) -> str:
        """
        Build the retrieved-documents block of the prompt.

        Args:
            documents: Search hits, best first
            query: The user's question
            max_tokens: Budget for the excerpts, counted in words

        Returns:
            Formatted context, or '' if no document contributed an excerpt
        """
        try:
            doc_chunks = cls._collect_chunks(documents, query)
        except Exception as e:
            logger.error(f"Building chunk context failed: {e}", exc_info=True)
            return ""

        if not doc_chunks:
            return ""

        parts = ["## Relevant information from the knowledge base:\n"]
        total_tokens = 0

        for doc_idx, (title, chunks) in enumerate(doc_chunks, 1):
            parts.append(f"\n### Document {doc_idx}: {title}")

            for chunk_idx, chunk_text in enumerate(chunks, 1):
                chunk_tokens = len(chunk_text.split())
                if total_tokens + chunk_tokens > max_tokens:
                    remaining = max_tokens - total_tokens
                    if remaining > 50:
                        clipped = " ".join(chunk_text.split()[:remaining]) + "..."
                        parts.append(f"\n[Excerpt {chunk_idx}]\n{clipped}")
                    parts.append(
                        "\n\n[More relevant information exists but the context "
                        "limit was reached]"
                    )
                    return "\n".join(parts)

                parts.append(f"\n[Excerpt {chunk_idx}]\n{chunk_text}")
                total_tokens += chunk_tokens

        logger.info(
            f"Chunk context built: {len(doc_chunks)} documents, {total_tokens} words"
        )
        return "\n".join(parts)

    @classmethod
    def _collect_chunks(
        cls, documents: List[KnowledgeDocument], query: str
    ) -> List[Tuple[str, List[str]]]:
        """(title, [excerpt, ...]) per document, in the order of `documents`."""
        fts_query = QueryProcessor.preprocess_for_fts5(query)
        collected: List[Tuple[str, List[str]]] = []

        with get_db_connection() as conn:
            for doc in documents:
                title = doc.title or doc.original_filename

                if _is_bookstack_document(doc):
                    # The search already fetched the matching chunks' full text;
                    # a page found only as a whole falls back to its snippet.
                    texts = list(getattr(doc, "bookstack_chunks", None) or [])
                    if not texts:
                        snippet = _clean_snippet(getattr(doc, "search_snippet", ""))
                        texts = [snippet] if snippet else []
                elif fts_query:
                    rows = conn.execute(
                        """
                        SELECT c.chunk_text
                        FROM kb_chunks_fts fts
                        JOIN kb_chunks c ON fts.rowid = c.id
                        WHERE kb_chunks_fts MATCH ?
                        AND c.doc_id = ?
                        ORDER BY rank
                        LIMIT ?
                        """,
                        (fts_query, doc.id, CHUNKS_PER_DOCUMENT),
                    ).fetchall()
                    texts = [row["chunk_text"] for row in rows]
                else:
                    texts = []

                texts = list(dict.fromkeys(t for t in texts if t))[:CHUNKS_PER_DOCUMENT]
                if texts:
                    collected.append((title, texts))

        return collected
