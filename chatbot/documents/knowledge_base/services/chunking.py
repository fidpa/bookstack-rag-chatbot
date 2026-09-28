"""Chunking for uploaded knowledge-base documents (overlapping word windows)."""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from utils.text_chunking import TextChunker, chunk_statistics

logger = logging.getLogger(__name__)


@dataclass
class DocumentChunk:
    """One chunk of an uploaded document."""

    text: str
    doc_id: int
    chunk_index: int
    start_pos: int
    end_pos: int
    word_count: int

    def to_dict(self) -> Dict:
        """Row values for the kb_chunks table."""
        return {
            "doc_id": self.doc_id,
            "chunk_index": self.chunk_index,
            "chunk_text": self.text,
            "start_pos": self.start_pos,
            "end_pos": self.end_pos,
        }


class ChunkingService:
    """Splits extracted document text into overlapping chunks.

    Larger windows than for wiki pages: uploads are long PDFs and manuals,
    where a chunk should hold a whole section.
    """

    DEFAULTS = {"chunk_size": 1000, "overlap": 200, "min_size": 100}

    def __init__(self, chunk_size: Optional[int] = None, overlap: Optional[int] = None):
        self.chunk_size = chunk_size or self.DEFAULTS["chunk_size"]
        self.overlap = overlap or self.DEFAULTS["overlap"]
        self._chunker = TextChunker(
            self.chunk_size, self.overlap, self.DEFAULTS["min_size"]
        )

    def chunk_document(self, text: str, doc_id: int) -> List[DocumentChunk]:
        """Split a document's text into overlapping chunks, indexed from 0."""
        chunks = [
            DocumentChunk(
                text=span.text,
                doc_id=doc_id,
                chunk_index=index,
                start_pos=span.start_pos,
                end_pos=span.end_pos,
                word_count=span.word_count,
            )
            for index, span in enumerate(self._chunker.split(text))
        ]
        logger.info(f"Document {doc_id} split into {len(chunks)} chunks")
        return chunks

    def get_chunk_statistics(self, chunks: List[DocumentChunk]) -> Dict:
        """Word-count statistics for a list of chunks."""
        return chunk_statistics(
            [c.word_count for c in chunks], self.overlap, self.chunk_size
        )
