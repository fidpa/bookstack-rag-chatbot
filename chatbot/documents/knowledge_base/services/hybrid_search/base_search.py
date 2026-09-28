"""
Search Implementation Functions
Contains the actual search implementations for different strategies
"""

import logging
from typing import Dict, List

from utils.database import get_db_connection
from ..query_processor.preprocessor import match_any, match_phrase
from .strategies import SearchStrategy, STRATEGY_WEIGHTS, relative_relevance
from .models import SearchResult

logger = logging.getLogger(__name__)


def bookstack_doc_id(bookstack_id: int, content_type: str) -> str:
    """One id per BookStack item, shared by its page-level and chunk hits.

    Fusion merges results by id; giving both searches the same id makes a page
    found by each count once, with both strategies credited.
    """
    return f"bookstack_{bookstack_id}_{content_type}"


class SearchImplementations:
    """Implementation of various search strategies"""

    STRATEGY_WEIGHTS = STRATEGY_WEIGHTS

    @classmethod
    def search_title_tags(
        cls, terms: List[str], active_only: bool
    ) -> List[SearchResult]:
        """Match terms against document titles, filenames and tags."""
        if not terms:
            return []

        results = []
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()

                where_clauses = []
                params = []
                for term in terms[:5]:
                    where_clauses.append(
                        "(LOWER(d.title) LIKE ? OR LOWER(d.original_filename) LIKE ? OR "
                        "EXISTS (SELECT 1 FROM kb_tags t WHERE t.document_id = d.id "
                        "AND LOWER(t.tag) LIKE ?))"
                    )
                    term_pattern = f"%{term.lower()}%"
                    params.extend([term_pattern, term_pattern, term_pattern])

                query = f"""
                    SELECT DISTINCT d.id, d.title, d.original_filename
                    FROM kb_documents d
                    WHERE ({' OR '.join(where_clauses)})
                    {'AND d.is_active = 1' if active_only else ''}
                """
                cursor.execute(query, params)

                for row in cursor.fetchall():
                    results.append(
                        SearchResult(
                            doc_id=row["id"],
                            doc_title=row["title"] or row["original_filename"],
                            doc_filename=row["original_filename"],
                            relevance_score=STRATEGY_WEIGHTS[SearchStrategy.TITLE_TAG],
                            match_type=SearchStrategy.TITLE_TAG,
                            snippet="",
                        )
                    )

        except Exception as e:
            logger.error(f"Title/tag search failed: {e}")

        return results

    @classmethod
    def _kb_chunk_hits(
        cls,
        fts_query: str,
        active_only: bool,
        strategy: SearchStrategy,
        limit: int = 100,
    ) -> List[SearchResult]:
        """Run one MATCH over kb_chunks and fold the hits into one result per document."""
        if not fts_query:
            return []

        with get_db_connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    c.doc_id,
                    c.chunk_index,
                    d.title,
                    d.original_filename,
                    snippet(kb_chunks_fts, 0, '', '', '...', 30) AS snippet,
                    rank
                FROM kb_chunks_fts fts
                JOIN kb_chunks c ON fts.rowid = c.id
                JOIN kb_documents d ON c.doc_id = d.id
                WHERE kb_chunks_fts MATCH ?
                AND (? = 0 OR d.is_active = 1)
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, 1 if active_only else 0, limit),
            ).fetchall()

        if not rows:
            return []

        best_rank = rows[0]["rank"]
        by_doc: Dict[int, SearchResult] = {}
        for row in rows:
            result = by_doc.get(row["doc_id"])
            if result is None:
                # Rows arrive best first, so the first row per document is its best
                result = SearchResult(
                    doc_id=row["doc_id"],
                    doc_title=row["title"] or row["original_filename"],
                    doc_filename=row["original_filename"],
                    relevance_score=STRATEGY_WEIGHTS[strategy]
                    * relative_relevance(row["rank"], best_rank),
                    match_type=strategy,
                    snippet=row["snippet"],
                )
                by_doc[row["doc_id"]] = result
            result.matched_chunks.append(
                {"chunk_index": row["chunk_index"], "rank": row["rank"]}
            )
        return list(by_doc.values())

    @classmethod
    def search_exact_phrase(
        cls, terms: List[str], active_only: bool
    ) -> List[SearchResult]:
        """Documents containing the terms as one consecutive phrase."""
        try:
            return cls._kb_chunk_hits(
                match_phrase(terms), active_only, SearchStrategy.EXACT_PHRASE, limit=50
            )
        except Exception as e:
            logger.error(f"Exact phrase search failed: {e}")
            return []

    @classmethod
    def search_keywords_or(
        cls, keywords: List[str], active_only: bool
    ) -> List[SearchResult]:
        """Documents containing any of the keywords."""
        try:
            results = cls._kb_chunk_hits(
                match_any(keywords[:5]), active_only, SearchStrategy.KEYWORD_OR
            )
        except Exception as e:
            logger.error(f"Keyword OR search failed: {e}")
            return []

        # A document matching in many chunks is more likely to be about the topic
        for result in results:
            result.relevance_score *= 1 + min(len(result.matched_chunks) / 10, 1)
        return results

    @classmethod
    def search_bookstack_content(
        cls, terms: List[str], active_only: bool = True
    ) -> List[SearchResult]:
        """
        Search whole BookStack items (title, text, tags).

        Args:
            terms: Search terms
            active_only: Unused; BookStack items have no active flag

        Returns:
            One result per matching book, chapter or page
        """
        fts_query = match_any(terms[:5])
        if not fts_query:
            return []

        results = []
        try:
            with get_db_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT
                        bc.bookstack_id,
                        bc.type,
                        bc.title,
                        bc.url,
                        snippet(bookstack_fts, 1, '', '', '...', 64) AS snippet,
                        rank
                    FROM bookstack_fts fts
                    JOIN bookstack_content bc ON fts.rowid = bc.id
                    WHERE bookstack_fts MATCH ?
                    ORDER BY rank
                    LIMIT 10
                    """,
                    (fts_query,),
                ).fetchall()

            best_rank = rows[0]["rank"] if rows else 0
            for row in rows:
                results.append(
                    SearchResult(
                        doc_id=bookstack_doc_id(row["bookstack_id"], row["type"]),
                        doc_title=row["title"],
                        doc_filename=f"BookStack {row['type']}: {row['title']}",
                        relevance_score=STRATEGY_WEIGHTS[SearchStrategy.KEYWORD_OR]
                        * relative_relevance(row["rank"], best_rank),
                        match_type=SearchStrategy.KEYWORD_OR,
                        snippet=row["snippet"] or "",
                        metadata={
                            "source": "bookstack",
                            "bookstack_id": row["bookstack_id"],
                            "content_type": row["type"],
                            "url": row["url"],
                        },
                    )
                )

        except Exception as e:
            logger.error(f"BookStack content search failed: {e}")

        return results

    @classmethod
    def search_bookstack_chunks(
        cls, terms: List[str], active_only: bool = True
    ) -> List[SearchResult]:
        """
        Search BookStack chunks and return one result per item with its best chunks.

        Args:
            terms: Search terms
            active_only: Unused; BookStack items have no active flag

        Returns:
            Results whose matched_chunks carry the full chunk text, best first
        """
        fts_query = match_any(terms[:5])
        if not fts_query:
            return []

        try:
            with get_db_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT
                        bc.bookstack_id,
                        bc.content_type,
                        bc.title,
                        bc.url,
                        bc.chunk_index,
                        bc.chunk_text,
                        rank
                    FROM bookstack_chunks_fts fts
                    JOIN bookstack_chunks bc ON fts.rowid = bc.id
                    WHERE bookstack_chunks_fts MATCH ?
                    ORDER BY rank
                    LIMIT 15
                    """,
                    (fts_query,),
                ).fetchall()
        except Exception as e:
            logger.error(f"BookStack chunk search failed: {e}")
            return []

        if not rows:
            return []

        best_rank = rows[0]["rank"]
        by_item: Dict[str, SearchResult] = {}
        for row in rows:
            doc_id = bookstack_doc_id(row["bookstack_id"], row["content_type"])
            result = by_item.get(doc_id)
            if result is None:
                result = SearchResult(
                    doc_id=doc_id,
                    doc_title=row["title"],
                    doc_filename=f"BookStack {row['content_type']}: {row['title']}",
                    relevance_score=STRATEGY_WEIGHTS[SearchStrategy.CHUNK_BASED]
                    * relative_relevance(row["rank"], best_rank),
                    match_type=SearchStrategy.CHUNK_BASED,
                    metadata={
                        "source": "bookstack",
                        "bookstack_id": row["bookstack_id"],
                        "content_type": row["content_type"],
                        "url": row["url"],
                    },
                )
                by_item[doc_id] = result
            result.matched_chunks.append(
                {
                    "chunk_index": row["chunk_index"],
                    "chunk_text": row["chunk_text"],
                    "rank": row["rank"],
                }
            )
        return list(by_item.values())
