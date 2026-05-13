"""Chunking Service für Knowledge Base - Teilt Dokumente in überlappende Chunks für optimale Suche und LLM-Verarbeitung"""
import re
import logging
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class DocumentChunk:
    """Repräsentiert einen einzelnen Dokument-Chunk"""
    text: str
    doc_id: int
    chunk_index: int
    start_pos: int
    end_pos: int
    word_count: int
    
    def to_dict(self) -> Dict:
        """Konvertiert zu Dictionary für DB-Speicherung"""
        return {
            'doc_id': self.doc_id,
            'chunk_index': self.chunk_index,
            'chunk_text': self.text,
            'start_pos': self.start_pos,
            'end_pos': self.end_pos
        }


class ChunkingService:
    """Service für Text Chunking und Content Processing"""
    
    # Chunking-Konfiguration: [chunk_size, overlap, min_size]
    DEFAULTS = {'chunk_size': 1000, 'overlap': 200, 'min_size': 100}
    
    def __init__(self, chunk_size: int = None, overlap: int = None):
        """Initialisiert den Chunking Service mit chunk_size und overlap"""
        self.chunk_size = chunk_size or self.DEFAULTS['chunk_size']
        self.overlap = overlap or self.DEFAULTS['overlap']
        # Validierung
        if self.overlap >= self.chunk_size:
            raise ValueError("Overlap muss kleiner als chunk_size sein")
        if self.chunk_size < self.DEFAULTS['min_size']:
            raise ValueError(f"chunk_size muss mindestens {self.DEFAULTS['min_size']} sein")
    
    def chunk_document(self, text: str, doc_id: int) -> List[DocumentChunk]:
        """Teilt ein Dokument in überlappende Chunks"""
        if not text or not text.strip():
            logger.warning(f"Leerer Text für Dokument {doc_id}")
            return []
        
        # Text vorbereiten
        text = self._normalize_whitespace(text)
        
        # In Sätze aufteilen für semantische Grenzen
        sentences = self._split_into_sentences(text)
        
        if not sentences:
            logger.warning(f"Keine Sätze in Dokument {doc_id} gefunden")
            return []
        
        # Chunks erstellen
        chunks = self._create_chunks_from_sentences(sentences, doc_id)
        
        # Optimierung: Sehr kleine Chunks mergen
        chunks = self._optimize_chunks(chunks)
        
        logger.info(f"Dokument {doc_id} in {len(chunks)} Chunks aufgeteilt")
        return chunks
    
    def _normalize_whitespace(self, text: str) -> str:
        """Normalisiert Whitespace im Text"""
        # Mehrfache Leerzeichen/Tabs zu einem Leerzeichen
        text = re.sub(r'\s+', ' ', text)
        # Mehrfache Zeilenumbrüche zu Doppel-Newline
        text = re.sub(r'\n\n+', '\n\n', text)
        return text.strip()
    
    def _split_into_sentences(self, text: str) -> List[Tuple[int, int, str]]:
        """Teilt Text in Sätze mit Positionen - Returns: Liste von (start_pos, end_pos, sentence)"""
        # Erweiterte Satzerkennung für Deutsch
        sentence_endings = re.compile(
            r'([.!?])\s+(?=[A-ZÄÖÜ])|'  # Normale Satzenden
            r'([.!?])\s*\n+|'            # Satzende mit Newline
            r'\n\n+'                      # Doppelte Newlines als Absatzgrenzen
        )
        
        sentences = []
        start = 0
        
        for match in sentence_endings.finditer(text):
            end = match.end()
            sentence = text[start:end].strip()
            
            if sentence:
                sentences.append((start, end, sentence))
            start = end
        
        # Letzten Satz hinzufügen
        if start < len(text):
            sentence = text[start:].strip()
            if sentence:
                sentences.append((start, len(text), sentence))
        
        return sentences
    
    def _create_chunks_from_sentences(self, sentences: List[Tuple[int, int, str]], 
                                     doc_id: int) -> List[DocumentChunk]:
        """Erstellt Chunks aus Sätzen mit Überlappung"""
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
                    current_chunk_sentences, doc_id, chunk_index
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
                current_chunk_sentences, doc_id, chunk_index
            )
            chunks.append(chunk)
        
        return chunks
    
    def _create_chunk_from_sentences(self, sentences: List[Tuple[int, int, str]], 
                                    doc_id: int, chunk_index: int) -> DocumentChunk:
        """Erstellt einen DocumentChunk aus Sätzen"""
        if not sentences:
            raise ValueError("Keine Sätze für Chunk vorhanden")
        
        # Text zusammenführen
        chunk_text = ' '.join(s[2] for s in sentences)
        
        # Positionen
        start_pos = sentences[0][0]
        end_pos = sentences[-1][1]
        
        # Wortanzahl
        word_count = len(chunk_text.split())
        
        return DocumentChunk(
            text=chunk_text,
            doc_id=doc_id,
            chunk_index=chunk_index,
            start_pos=start_pos,
            end_pos=end_pos,
            word_count=word_count
        )
    
    def _optimize_chunks(self, chunks: List[DocumentChunk]) -> List[DocumentChunk]:
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
                if combined_word_count <= self.chunk_size * 1.2:  # 20% Toleranz
                    # Chunks mergen
                    merged_chunk = DocumentChunk(
                        text=current_chunk.text + ' ' + next_chunk.text,
                        doc_id=current_chunk.doc_id,
                        chunk_index=current_chunk.chunk_index,
                        start_pos=current_chunk.start_pos,
                        end_pos=next_chunk.end_pos,
                        word_count=combined_word_count
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
    
    def get_chunk_statistics(self, chunks: List[DocumentChunk]) -> Dict:
        """Berechnet Statistiken für eine Liste von Chunks"""
        if not chunks:
            return {
                'total_chunks': 0,
                'avg_words_per_chunk': 0,
                'min_words': 0,
                'max_words': 0,
                'total_words': 0
            }
        
        word_counts = [chunk.word_count for chunk in chunks]
        
        return {
            'total_chunks': len(chunks),
            'avg_words_per_chunk': sum(word_counts) / len(word_counts),
            'min_words': min(word_counts),
            'max_words': max(word_counts),
            'total_words': sum(word_counts),
            'overlap_ratio': self.overlap / self.chunk_size
        }
    
    def validate_chunks(self, chunks: List[DocumentChunk]) -> Tuple[bool, List[str]]:
        """Validiert eine Liste von Chunks - Returns: (is_valid, error_messages)"""
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
        
        return len(errors) == 0, errors