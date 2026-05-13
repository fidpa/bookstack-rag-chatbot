"""
File Operations für Storage Service
Verwaltet Datei-Operationen wie Speichern, Löschen und Duplikat-Prüfung
"""

import os
import hashlib
import logging
from datetime import datetime
from typing import Optional, Tuple
from werkzeug.datastructures import FileStorage

from ...models import KnowledgeDocument
from ...validators import sanitize_filename
from utils.database import get_db_connection
# flask_login removed - Widget-Only architecture

logger = logging.getLogger(__name__)

def calculate_file_hash(file_content: bytes) -> str:
    """Berechnet den SHA256 Hash einer Datei"""
    return hashlib.sha256(file_content).hexdigest()

def check_duplicate(content_hash: str) -> Optional[KnowledgeDocument]:
    """Prüft ob ein Dokument mit diesem Hash bereits existiert"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM kb_documents 
            WHERE content_hash = ?
        ''', (content_hash,))
        
        row = cursor.fetchone()
        if row:
            return KnowledgeDocument.from_db_row(dict(row))
    return None

def save_file(file: FileStorage, title: str = "", description: str = "", tags: list = None) -> Tuple[bool, str, Optional[KnowledgeDocument]]:
    """
    Speichert eine Datei permanent in der Wissensbasis
    
    Returns:
        (success, message, document)
    """
    from .core import StorageService
    from .metadata import _extract_markdown_metadata
    
    if tags is None:
        tags = []
        
    try:
        StorageService.ensure_storage_directory()
        
        # Datei lesen und Hash berechnen
        file_content = file.read()
        file.seek(0)  # Zurück zum Anfang für weitere Operationen
        
        content_hash = calculate_file_hash(file_content)
        
        # Prüfe auf Duplikate
        existing_doc = check_duplicate(content_hash)
        if existing_doc:
            return False, f"Dokument bereits vorhanden: {existing_doc.original_filename}", existing_doc
        
        # Sichere Dateinamen generieren
        original_filename = file.filename
        extension = original_filename.rsplit('.', 1)[-1].lower() if '.' in original_filename else ''
        safe_filename = f"{content_hash[:16]}_{sanitize_filename(original_filename)}"
        file_path = os.path.join(StorageService.STORAGE_BASE_PATH, safe_filename)
        
        # Datei speichern
        file.save(file_path)
        
        # Dateigröße ermitteln
        file_size = os.path.getsize(file_path)
        
        # Bei Markdown-Dateien: Frontmatter extrahieren
        if extension == 'md':
            extracted_metadata = _extract_markdown_metadata(file_path)
            if extracted_metadata:
                # Überschreibe Metadaten mit Frontmatter-Werten
                title = extracted_metadata.get('title', title) or title
                description = extracted_metadata.get('description', description) or description
                # Tags könnten auch aus Frontmatter kommen
                frontmatter_tags = extracted_metadata.get('tags', [])
        
        # In Datenbank eintragen
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO kb_documents 
                (filename, original_filename, file_path, file_size, file_type, 
                 title, description, content_hash, uploaded_by, uploaded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                safe_filename,
                original_filename,
                file_path,
                file_size,
                extension,
                title or original_filename,
                description,
                content_hash,
                0,  # Fixed system user for widget-only architecture
                datetime.now().isoformat()
            ))
            
            doc_id = cursor.lastrowid
            
            # Tags speichern (aus Frontmatter oder manuell)
            all_tags = []
            if extension == 'md' and 'frontmatter_tags' in locals() and frontmatter_tags:
                all_tags.extend(frontmatter_tags)
            if tags:  # Manuelle Tags
                all_tags.extend(tags)
            
            # Deduplizieren und speichern
            unique_tags = list(set(tag.strip() for tag in all_tags if tag.strip()))
            for tag in unique_tags:
                cursor.execute('''
                    INSERT INTO kb_tags (document_id, tag)
                    VALUES (?, ?)
                ''', (doc_id, tag))
            
            conn.commit()
            
            # Dokument-Objekt erstellen
            document = KnowledgeDocument(
                id=doc_id,
                filename=safe_filename,
                original_filename=original_filename,
                file_path=file_path,
                file_size=file_size,
                file_type=extension,
                title=title or original_filename,
                description=description,
                content_hash=content_hash,
                uploaded_by="system",  # Fixed system user for widget-only architecture
                uploaded_at=datetime.now()
            )
            
            logger.info(f"Dokument erfolgreich gespeichert: {original_filename} -> {safe_filename}")
            return True, "Dokument erfolgreich gespeichert", document
            
    except Exception as e:
        logger.error(f"Fehler beim Speichern des Dokuments: {str(e)}")
        return False, f"Fehler beim Speichern: {str(e)}", None

def delete_file(doc_id: int) -> Tuple[bool, str]:
    """
    Löscht ein Dokument aus der Wissensbasis
    
    Returns:
        (success, message)
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Dokument-Info abrufen
            cursor.execute('SELECT file_path FROM kb_documents WHERE id = ?', (doc_id,))
            row = cursor.fetchone()
            
            if not row:
                return False, "Dokument nicht gefunden"
            
            file_path = row['file_path']
            
            # Aus Datenbank löschen
            cursor.execute('DELETE FROM kb_documents WHERE id = ?', (doc_id,))
            cursor.execute('DELETE FROM kb_search_fts WHERE doc_id = ?', (doc_id,))
            cursor.execute('DELETE FROM kb_tags WHERE document_id = ?', (doc_id,))
            
            # Datei löschen
            if os.path.exists(file_path):
                os.remove(file_path)
            
            conn.commit()
            
            logger.info(f"Dokument {doc_id} erfolgreich gelöscht")
            return True, "Dokument erfolgreich gelöscht"
            
    except Exception as e:
        logger.error(f"Fehler beim Löschen des Dokuments {doc_id}: {str(e)}")
        return False, f"Fehler beim Löschen: {str(e)}"

def get_document_by_id(doc_id: int) -> Optional[KnowledgeDocument]:
    """
    Lädt ein Dokument anhand seiner ID
    
    Returns:
        KnowledgeDocument oder None
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM kb_documents WHERE id = ?', (doc_id,))
            row = cursor.fetchone()
            
            if row:
                return KnowledgeDocument.from_db_row(dict(row))
                
    except Exception as e:
        logger.error(f"Fehler beim Laden des Dokuments {doc_id}: {str(e)}")
        
    return None