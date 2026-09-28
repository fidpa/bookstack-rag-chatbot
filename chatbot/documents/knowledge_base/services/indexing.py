"""
Indexing Service for the knowledge base
Extracts text from uploaded documents and stores it as searchable chunks.
"""

import os
import logging
from datetime import datetime
from typing import Tuple

from utils.database import get_db_connection
from ..models import KnowledgeDocument
from .chunking import ChunkingService

logger = logging.getLogger(__name__)


def _extract_text_from_file(file_path: str, file_type: str) -> str:
    """Extract plain text from a file based on its MIME type or extension."""
    ft = file_type.lower()

    # PDF
    if "pdf" in ft or file_path.lower().endswith(".pdf"):
        try:
            import pypdfium2 as pdfium

            doc = pdfium.PdfDocument(file_path)
            pages = [doc[i].get_textpage().get_text_range() for i in range(len(doc))]
            return "\n\n".join(pages)
        except Exception:
            pass
        try:
            from pypdf import PdfReader

            reader = PdfReader(file_path)
            return "\n\n".join(p.extract_text() or "" for p in reader.pages)
        except Exception as e:
            raise RuntimeError(f"PDF extraction failed: {e}") from e

    # DOCX
    if "wordprocessingml" in ft or "docx" in ft or file_path.lower().endswith(".docx"):
        try:
            from docx import Document

            doc = Document(file_path)
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception as e:
            raise RuntimeError(f"DOCX extraction failed: {e}") from e

    # Plain text / Markdown
    if "text" in ft or file_path.lower().endswith((".md", ".txt", ".markdown")):
        with open(file_path, encoding="utf-8", errors="replace") as fh:
            return fh.read()

    raise ValueError(f"Unsupported file type: {file_type}")


class IndexingService:
    """Full-text indexing of uploaded knowledge-base documents"""

    @classmethod
    def extract_text_from_document(cls, doc: KnowledgeDocument) -> Tuple[bool, str]:
        """
        Extract the plain text of a document.

        Returns:
            (success, text_content)
        """
        try:
            if not os.path.exists(doc.file_path):
                logger.error(f"File not found: {doc.file_path}")
                return False, f"File not found: {doc.file_path}"

            logger.info(f"Extracting text from: {doc.file_path}")
            text = _extract_text_from_file(doc.file_path, doc.file_type)

            if not text or not text.strip():
                logger.warning(f"Empty text extracted for {doc.original_filename}")
                return False, "No text extracted"

            logger.info(
                f"Text extraction successful for {doc.original_filename}: {len(text)} chars"
            )
            return True, text

        except Exception as e:
            error_msg = f"Text extraction failed for {doc.original_filename}: {e}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg

    @classmethod
    def index_document(cls, doc_id: int) -> Tuple[bool, str]:
        """
        Extract, chunk and index one uploaded document.

        On failure the document's chunking_status is set to 'failed', which is
        what `kb_admin.py bulk reindex` selects.

        Args:
            doc_id: kb_documents id

        Returns:
            (success, message)
        """
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()

                # Dokument laden
                cursor.execute("SELECT * FROM kb_documents WHERE id = ?", (doc_id,))
                row = cursor.fetchone()

                if not row:
                    return False, "Document not found"

                doc = KnowledgeDocument.from_db_row(dict(row))

            success, text_content = cls.extract_text_from_document(doc)
            if success:
                success, message = cls._index_with_chunking(doc_id, text_content)
            else:
                message = f"Text extraction failed: {text_content}"

        except Exception as e:
            success, message = False, f"Indexing failed: {e}"

        if not success:
            logger.error(f"Indexing document {doc_id} failed: {message}")
            cls._mark_failed(doc_id)
        return success, message

    @classmethod
    def _mark_failed(cls, doc_id: int):
        try:
            with get_db_connection() as conn:
                conn.execute(
                    "UPDATE kb_documents SET chunking_status = 'failed' WHERE id = ?",
                    (doc_id,),
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Could not mark document {doc_id} as failed: {e}")

    @classmethod
    def _index_with_chunking(cls, doc_id: int, text_content: str) -> Tuple[bool, str]:
        """Index document using the chunking pipeline."""
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()

                cursor.execute("DELETE FROM kb_chunks WHERE doc_id = ?", (doc_id,))

                chunking_service = ChunkingService()
                chunks = chunking_service.chunk_document(text_content, doc_id)

                if not chunks:
                    logger.warning(f"No chunks created for document {doc_id}")
                    return False, "No chunks created"

                for chunk in chunks:
                    chunk_dict = chunk.to_dict()
                    cursor.execute(
                        """
                        INSERT INTO kb_chunks
                        (doc_id, chunk_index, chunk_text, start_pos, end_pos, word_count)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """,
                        (
                            chunk_dict["doc_id"],
                            chunk_dict["chunk_index"],
                            chunk_dict["chunk_text"],
                            chunk_dict["start_pos"],
                            chunk_dict["end_pos"],
                            chunk.word_count,
                        ),
                    )

                cursor.execute(
                    """
                    UPDATE kb_documents
                    SET last_indexed = ?,
                        chunking_status = 'completed',
                        chunk_count = ?
                    WHERE id = ?
                """,
                    (datetime.now().isoformat(), len(chunks), doc_id),
                )

                conn.commit()

                logger.info(f"Document {doc_id} indexed with {len(chunks)} chunks")
                return True, f"Document indexed ({len(chunks)} chunks)"

        except Exception as e:
            logger.error(f"Chunk indexing error: {e}", exc_info=True)
            return False, f"Chunk indexing failed: {e}"
