"""Chunking service tuned for BookStack content (overlapping word windows)."""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from utils.text_chunking import TextChunker, chunk_statistics

logger = logging.getLogger(__name__)


@dataclass
class BookStackChunk:
    """One chunk of a BookStack page, chapter or book."""

    text: str
    bookstack_id: int
    content_type: str  # 'page', 'chapter', 'book'
    chunk_index: int
    start_pos: int
    end_pos: int
    word_count: int

    title: str = ""
    url: str = ""
    book_id: Optional[int] = None
    chapter_id: Optional[int] = None

    def to_dict(self) -> Dict:
        """Row values for the bookstack_chunks table."""
        return {
            "bookstack_id": self.bookstack_id,
            "content_type": self.content_type,
            "chunk_index": self.chunk_index,
            "chunk_text": self.text,
            "start_pos": self.start_pos,
            "end_pos": self.end_pos,
            "word_count": self.word_count,
            "title": self.title,
            "url": self.url,
            "book_id": self.book_id,
            "chapter_id": self.chapter_id,
        }


class BookStackChunkingService:
    """Splits cleaned BookStack text into overlapping, word-counted chunks."""

    DEFAULTS = {
        "chunk_size": 800,  # words per chunk
        "overlap": 150,  # words carried into the next chunk (~19%)
        "min_size": 80,  # chunks below this are merged into their neighbour
    }

    def __init__(self, chunk_size: Optional[int] = None, overlap: Optional[int] = None):
        self.chunk_size = chunk_size or self.DEFAULTS["chunk_size"]
        self.overlap = overlap or self.DEFAULTS["overlap"]
        self._chunker = TextChunker(
            self.chunk_size, self.overlap, self.DEFAULTS["min_size"]
        )

    def chunk_bookstack_content(
        self,
        text: str,
        bookstack_id: int,
        content_type: str,
        title: str = "",
        url: str = "",
        book_id: Optional[int] = None,
        chapter_id: Optional[int] = None,
    ) -> List[BookStackChunk]:
        """
        Split BookStack content into overlapping chunks.

        Args:
            text: Cleaned text; line breaks mark paragraph and block boundaries
            bookstack_id: ID of the BookStack item
            content_type: 'page', 'chapter' or 'book'
            title: Item title
            url: BookStack URL
            book_id: Parent book ID
            chapter_id: Parent chapter ID

        Returns:
            List of chunks, indexed from 0
        """
        return [
            BookStackChunk(
                text=span.text,
                bookstack_id=bookstack_id,
                content_type=content_type,
                chunk_index=index,
                start_pos=span.start_pos,
                end_pos=span.end_pos,
                word_count=span.word_count,
                title=title,
                url=url,
                book_id=book_id,
                chapter_id=chapter_id,
            )
            for index, span in enumerate(self._chunker.split(text))
        ]

    def get_chunk_statistics(self, chunks: List[BookStackChunk]) -> Dict:
        """Word-count statistics for a list of chunks."""
        return chunk_statistics(
            [c.word_count for c in chunks], self.overlap, self.chunk_size
        )

    def validate_chunks(self, chunks: List[BookStackChunk]) -> Tuple[bool, List[str]]:
        """Check chunk invariants; returns (valid, errors)."""
        errors = []

        for i, chunk in enumerate(sorted(chunks, key=lambda c: c.chunk_index)):
            if not chunk.text or not chunk.text.strip():
                errors.append(f"chunk {i} has no text")
            if chunk.word_count < 1:
                errors.append(f"chunk {i} has an invalid word count")
            if chunk.start_pos >= chunk.end_pos:
                errors.append(f"chunk {i} has invalid positions")
            if chunk.chunk_index != i:
                errors.append(f"chunk index {chunk.chunk_index} where {i} was expected")
            if chunk.content_type not in ("page", "chapter", "book"):
                errors.append(
                    f"chunk {i} has invalid content_type {chunk.content_type}"
                )
            if chunk.bookstack_id <= 0:
                errors.append(
                    f"chunk {i} has invalid bookstack_id {chunk.bookstack_id}"
                )

        return not errors, errors
