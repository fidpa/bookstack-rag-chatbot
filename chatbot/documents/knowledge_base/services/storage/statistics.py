"""
Statistics Operations für Storage Service
Verwaltet Statistik-Operationen wie Chunk-Statistiken
"""

import logging
from typing import Dict

from utils.database import get_db_connection

logger = logging.getLogger(__name__)

def get_chunk_stats(doc_id: int) -> Dict:
    """
    Holt Chunk-Statistiken für ein Dokument
    
    Returns:
        Dict mit total_chunks, avg_size, min_size, max_size
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Prüfe zuerst ob es Chunks gibt
            cursor.execute('''
                SELECT COUNT(*) as total,
                       AVG(LENGTH(chunk_text)) as avg_size,
                       MIN(LENGTH(chunk_text)) as min_size,
                       MAX(LENGTH(chunk_text)) as max_size
                FROM kb_chunks
                WHERE doc_id = ?
            ''', (doc_id,))
            
            row = cursor.fetchone()
            if row and row['total'] > 0:
                return {
                    'total_chunks': row['total'],
                    'avg_size': int(row['avg_size']) if row['avg_size'] else 0,
                    'min_size': row['min_size'] or 0,
                    'max_size': row['max_size'] or 0
                }
            
            # Fallback: Prüfe kb_chunk_stats Tabelle
            cursor.execute('''
                SELECT total_chunks, avg_chunk_size, min_chunk_size, max_chunk_size
                FROM kb_chunk_stats
                WHERE doc_id = ?
            ''', (doc_id,))
            
            row = cursor.fetchone()
            if row:
                return {
                    'total_chunks': row['total_chunks'] or 0,
                    'avg_size': row['avg_chunk_size'] or 0,
                    'min_size': row['min_chunk_size'] or 0,
                    'max_size': row['max_chunk_size'] or 0
                }
            
            return {
                'total_chunks': 0,
                'avg_size': 0,
                'min_size': 0,
                'max_size': 0
            }
            
    except Exception as e:
        logger.error(f"Fehler beim Laden der Chunk-Stats für Dokument {doc_id}: {str(e)}")
        return {
            'total_chunks': 0,
            'avg_size': 0,
            'min_size': 0,
            'max_size': 0
        }