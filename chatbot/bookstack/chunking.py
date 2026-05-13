"""Chunking service tuned for BookStack content (overlapping word windows)."""

import re
import logging
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class BookStackChunk:
    """Repräsentiert einen einzelnen BookStack-Content-Chunk"""
    text: str
    bookstack_id: int
    content_type: str  # 'page', 'chapter', 'book'
    chunk_index: int
    start_pos: int
    end_pos: int
    word_count: int

    # BookStack-spezifische Felder
    title: str = ""
    url: str = ""
    book_id: Optional[int] = None
    chapter_id: Optional[int] = None

    def to_dict(self) -> Dict:
        """Konvertiert zu Dictionary für DB-Speicherung"""
        return {
            'bookstack_id': self.bookstack_id,
            'content_type': self.content_type,
            'chunk_index': self.chunk_index,
            'chunk_text': self.text,
            'start_pos': self.start_pos,
            'end_pos': self.end_pos,
            'word_count': self.word_count,
            'title': self.title,
            'url': self.url,
            'book_id': self.book_id,
            'chapter_id': self.chapter_id
        }


class BookStackChunkingService:
    """Service für BookStack Text Chunking und Content Processing"""

    # Chunking-Konfiguration optimiert für BookStack-Seiten
    DEFAULTS = {
        'chunk_size': 800,     # Etwas kleiner für bessere Retrieval-Präzision
        'overlap': 150,        # ~19% Overlap für gute Kontext-Erhaltung
        'min_size': 80         # Minimum für sinnvolle Chunks
    }

    def __init__(self, chunk_size: int = None, overlap: int = None):
        """Initialisiert den BookStack Chunking Service"""
        self.chunk_size = chunk_size or self.DEFAULTS['chunk_size']
        self.overlap = overlap or self.DEFAULTS['overlap']

        # Validierung
        if self.overlap >= self.chunk_size:
            raise ValueError("Overlap muss kleiner als chunk_size sein")
        if self.chunk_size < self.DEFAULTS['min_size']:
            raise ValueError(f"chunk_size muss mindestens {self.DEFAULTS['min_size']} sein")

        logger.info(f"BookStack Chunking Service initialisiert: {self.chunk_size} Wörter, {self.overlap} Overlap")

    def chunk_bookstack_content(self, text: str, bookstack_id: int, content_type: str,
                               title: str = "", url: str = "", book_id: int = None,
                               chapter_id: int = None) -> List[BookStackChunk]:
        """
        Teilt BookStack-Content in überlappende Chunks

        Args:
            text: Bereits bereinigter Text-Content
            bookstack_id: ID des BookStack-Elements
            content_type: 'page', 'chapter', oder 'book'
            title: Titel des Contents
            url: BookStack-URL
            book_id: Übergeordnete Book-ID
            chapter_id: Übergeordnete Chapter-ID

        Returns:
            Liste von BookStackChunk-Objekten
        """
        # Enhanced empty content check
        if not text or not text.strip() or len(text.strip()) < 10:
            logger.debug(f"Skipping empty/minimal content for BookStack {content_type} {bookstack_id} (length: {len(text.strip()) if text else 0})")
            return []

        # Text vorbereiten (weitere Optimierung für BookStack)
        text = self._normalize_bookstack_text(text)

        # In Sätze aufteilen für semantische Grenzen
        sentences = self._split_into_sentences(text)

        if not sentences:
            logger.warning(f"Keine Sätze in BookStack {content_type} {bookstack_id} gefunden")
            return []

        # Chunks erstellen
        chunks = self._create_chunks_from_sentences(
            sentences, bookstack_id, content_type, title, url, book_id, chapter_id
        )

        # Optimierung: Sehr kleine Chunks mergen
        chunks = self._optimize_chunks(chunks)

        logger.info(f"BookStack {content_type} {bookstack_id} in {len(chunks)} Chunks aufgeteilt")
        return chunks

    def _normalize_bookstack_text(self, text: str) -> str:
        """Normalisiert Text speziell für BookStack-Content"""
        # Mehrfache Leerzeichen/Tabs zu einem Leerzeichen
        text = re.sub(r'\s+', ' ', text)

        # Mehrfache Zeilenumbrüche zu Doppel-Newline
        text = re.sub(r'\n\n+', '\n\n', text)

        # BookStack-spezifische Bereinigungen
        # Entferne übriggebliebene HTML-Entities
        text = re.sub(r'&\w+;', ' ', text)

        # Entferne sehr kurze Zeilen (oft HTML-Reste)
        lines = text.split('\n')
        cleaned_lines = []
        for line in lines:
            if len(line.strip()) > 3 or line.strip() == '':
                cleaned_lines.append(line)

        return '\n'.join(cleaned_lines).strip()

    def _split_into_sentences(self, text: str) -> List[Tuple[int, int, str]]:
        """Teilt Text in Sätze mit Positionen - Returns: Liste von (start_pos, end_pos, sentence)"""
        # Erweiterte Satzerkennung für Deutsch/Englisch (BookStack kann multilingual sein)
        sentence_endings = re.compile(
            r'([.!?])\s+(?=[A-ZÄÖÜ])|'  # Normale Satzenden
            r'([.!?])\s*\n+|'            # Satzende mit Newline
            r'\n\n+|'                    # Doppelte Newlines als Absatzgrenzen
            r'([.!?])\s*$'               # Satzende am Textende
        )

        sentences = []
        start = 0

        for match in sentence_endings.finditer(text):
            end = match.end()
            sentence = text[start:end].strip()

            if sentence and len(sentence) > 10:  # Mindestlänge für sinnvolle Sätze
                sentences.append((start, end, sentence))
            start = end

        # Letzten Satz hinzufügen
        if start < len(text):
            sentence = text[start:].strip()
            if sentence and len(sentence) > 10:
                sentences.append((start, len(text), sentence))

        return sentences

    def _create_chunks_from_sentences(self, sentences: List[Tuple[int, int, str]],
                                     bookstack_id: int, content_type: str, title: str,
                                     url: str, book_id: int, chapter_id: int) -> List[BookStackChunk]:
        """Erstellt BookStack-Chunks aus Sätzen mit Überlappung"""
        chunks = []
        current_chunk_sentences = []
        current_word_count = 0
        chunk_index = 0

        for sent_start, sent_end, sentence in sentences:
            # Wörter im Satz zählen
            word_count = len(sentence.split())

            # Prüfen ob Chunk voll ist
            if current_word_count + word_count > self.chunk_size and current_chunk_sentences:
                # Chunk erstellen
                chunk = self._create_chunk_from_sentences(
                    current_chunk_sentences, bookstack_id, content_type, chunk_index,
                    title, url, book_id, chapter_id
                )
                chunks.append(chunk)
                chunk_index += 1

                # Overlap behalten
                overlap_sentences = []
                overlap_word_count = 0

                # Von hinten nach vorne durch Sätze gehen für Overlap
                for s in reversed(current_chunk_sentences):
                    s_word_count = len(s[2].split())
                    if overlap_word_count + s_word_count <= self.overlap:
                        overlap_sentences.insert(0, s)
                        overlap_word_count += s_word_count
                    else:
                        break

                current_chunk_sentences = overlap_sentences
                current_word_count = overlap_word_count

            # Satz hinzufügen
            current_chunk_sentences.append((sent_start, sent_end, sentence))
            current_word_count += word_count

        # Letzten Chunk hinzufügen
        if current_chunk_sentences:
            chunk = self._create_chunk_from_sentences(
                current_chunk_sentences, bookstack_id, content_type, chunk_index,
                title, url, book_id, chapter_id
            )
            chunks.append(chunk)

        return chunks

    def _create_chunk_from_sentences(self, sentences: List[Tuple[int, int, str]],
                                    bookstack_id: int, content_type: str, chunk_index: int,
                                    title: str, url: str, book_id: int, chapter_id: int) -> BookStackChunk:
        """Erstellt einen BookStackChunk aus Sätzen"""
        if not sentences:
            raise ValueError("Keine Sätze für Chunk vorhanden")

        # Text zusammenführen
        chunk_text = ' '.join(s[2] for s in sentences)

        # Positionen
        start_pos = sentences[0][0]
        end_pos = sentences[-1][1]

        # Wortanzahl
        word_count = len(chunk_text.split())

        return BookStackChunk(
            text=chunk_text,
            bookstack_id=bookstack_id,
            content_type=content_type,
            chunk_index=chunk_index,
            start_pos=start_pos,
            end_pos=end_pos,
            word_count=word_count,
            title=title,
            url=url,
            book_id=book_id,
            chapter_id=chapter_id
        )

    def _optimize_chunks(self, chunks: List[BookStackChunk]) -> List[BookStackChunk]:
        """Optimiert Chunks durch Mergen sehr kleiner Chunks"""
        if len(chunks) <= 1:
            return chunks

        optimized = []
        i = 0

        while i < len(chunks):
            current_chunk = chunks[i]

            # Prüfen ob Chunk zu klein ist
            if current_chunk.word_count < self.DEFAULTS['min_size'] and i < len(chunks) - 1:
                next_chunk = chunks[i + 1]

                # Mit nächstem Chunk mergen wenn Gesamtgröße OK
                combined_word_count = current_chunk.word_count + next_chunk.word_count
                if combined_word_count <= self.chunk_size * 1.3:  # 30% Toleranz für BookStack
                    # Chunks mergen
                    merged_chunk = BookStackChunk(
                        text=current_chunk.text + ' ' + next_chunk.text,
                        bookstack_id=current_chunk.bookstack_id,
                        content_type=current_chunk.content_type,
                        chunk_index=current_chunk.chunk_index,
                        start_pos=current_chunk.start_pos,
                        end_pos=next_chunk.end_pos,
                        word_count=combined_word_count,
                        title=current_chunk.title,
                        url=current_chunk.url,
                        book_id=current_chunk.book_id,
                        chapter_id=current_chunk.chapter_id
                    )
                    optimized.append(merged_chunk)
                    i += 2  # Überspringe nächsten Chunk
                    continue

            # Chunk behalten
            optimized.append(current_chunk)
            i += 1

        # Chunk-Indizes neu nummerieren
        for idx, chunk in enumerate(optimized):
            chunk.chunk_index = idx

        return optimized

    def get_chunk_statistics(self, chunks: List[BookStackChunk]) -> Dict:
        """Berechnet Statistiken für eine Liste von BookStack-Chunks"""
        if not chunks:
            return {
                'total_chunks': 0,
                'avg_words_per_chunk': 0,
                'min_words': 0,
                'max_words': 0,
                'total_words': 0,
                'content_types': {}
            }

        word_counts = [chunk.word_count for chunk in chunks]

        # Content-Type Verteilung
        content_types = {}
        for chunk in chunks:
            content_types[chunk.content_type] = content_types.get(chunk.content_type, 0) + 1

        return {
            'total_chunks': len(chunks),
            'avg_words_per_chunk': sum(word_counts) / len(word_counts),
            'min_words': min(word_counts),
            'max_words': max(word_counts),
            'total_words': sum(word_counts),
            'overlap_ratio': self.overlap / self.chunk_size,
            'content_types': content_types
        }

    def validate_chunks(self, chunks: List[BookStackChunk]) -> Tuple[bool, List[str]]:
        """Validiert eine Liste von BookStack-Chunks"""
        errors = []

        if not chunks:
            return True, []

        # Sortiere nach chunk_index für Validierung
        sorted_chunks = sorted(chunks, key=lambda c: c.chunk_index)

        for i, chunk in enumerate(sorted_chunks):
            # Prüfe ob Text vorhanden
            if not chunk.text or not chunk.text.strip():
                errors.append(f"Chunk {i} hat keinen Text")

            # Prüfe Wortanzahl
            if chunk.word_count < 1:
                errors.append(f"Chunk {i} hat ungültige Wortanzahl")

            # Prüfe Positionen
            if chunk.start_pos >= chunk.end_pos:
                errors.append(f"Chunk {i} hat ungültige Positionen")

            # Prüfe chunk_index Kontinuität
            if chunk.chunk_index != i:
                errors.append(f"Chunk hat falschen Index: erwartet {i}, gefunden {chunk.chunk_index}")

            # Prüfe BookStack-spezifische Felder
            if not chunk.content_type in ['page', 'chapter', 'book']:
                errors.append(f"Chunk {i} hat ungültigen content_type: {chunk.content_type}")

            if chunk.bookstack_id <= 0:
                errors.append(f"Chunk {i} hat ungültige bookstack_id: {chunk.bookstack_id}")

        return len(errors) == 0, errors