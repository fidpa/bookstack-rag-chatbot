"""
Validierung für Knowledge Base Uploads
"""

import os
from werkzeug.datastructures import FileStorage
from typing import Tuple

# Erlaubte Dateitypen (wie bei Chat-Dokumenten)
ALLOWED_EXTENSIONS = {
    'pdf': 'application/pdf',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'doc': 'application/msword',
    'txt': 'text/plain',
    'md': 'text/markdown',
    'csv': 'text/csv',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'xls': 'application/vnd.ms-excel'
}

# Maximale Dateigröße: 20MB für Wissensbasis
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB

def validate_file(file: FileStorage) -> Tuple[bool, str]:
    """
    Validiert eine hochgeladene Datei für die Wissensbasis
    
    Returns:
        (is_valid, error_message)
    """
    # Prüfe ob Datei vorhanden
    if not file or file.filename == '':
        return False, "Keine Datei ausgewählt"
    
    # Prüfe Dateierweiterung
    extension = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if extension not in ALLOWED_EXTENSIONS:
        return False, f"Dateityp '.{extension}' nicht erlaubt. Erlaubt sind: {', '.join(ALLOWED_EXTENSIONS.keys())}"
    
    # Prüfe Dateigröße
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)  # Zurück zum Anfang
    
    if file_size > MAX_FILE_SIZE:
        size_mb = file_size / (1024 * 1024)
        return False, f"Datei zu groß ({size_mb:.1f} MB). Maximum: 20 MB"
    
    if file_size == 0:
        return False, "Datei ist leer"
    
    return True, ""

def validate_metadata(title: str, description: str) -> Tuple[bool, str]:
    """
    Validiert die Metadaten eines Dokuments
    
    Returns:
        (is_valid, error_message)
    """
    # Titel ist optional, aber wenn vorhanden, muss er gültig sein
    if title and len(title.strip()) > 255:
        return False, "Titel darf maximal 255 Zeichen lang sein"
    
    # Beschreibung ist optional, aber wenn vorhanden, muss sie gültig sein
    if description and len(description.strip()) > 1000:
        return False, "Beschreibung darf maximal 1000 Zeichen lang sein"
    
    return True, ""

def sanitize_filename(filename: str) -> str:
    """
    Bereinigt einen Dateinamen für sichere Speicherung
    """
    # Entferne potentiell gefährliche Zeichen
    import re
    # Erlaube nur alphanumerische Zeichen, Bindestriche, Unterstriche und Punkte
    sanitized = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)
    
    # Verhindere Directory Traversal
    sanitized = sanitized.replace('..', '_')
    
    # Begrenze Länge
    name, ext = os.path.splitext(sanitized)
    if len(name) > 100:
        name = name[:100]
    
    return f"{name}{ext}"