"""
Export Service für Knowledge Base
Verwaltet Export-Funktionalität für Dokumente und Metadaten
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict
from utils.database import get_db_connection
from .storage import StorageService

logger = logging.getLogger(__name__)


class ExportService:
    """Service für Export-Operationen der Wissensbasis"""

    @classmethod
    def export_metadata(cls) -> Dict:
        """
        Sammelt alle Metadaten für den Export

        Returns:
            Dict mit documents, statistics und tags
        """
        metadata = {"documents": [], "statistics": {}, "tags": {}}

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()

                # Alle Dokumente mit Metadaten
                cursor.execute("""
                    SELECT * FROM kb_documents 
                    ORDER BY uploaded_at DESC
                """)

                for row in cursor.fetchall():
                    doc_data = dict(row)
                    doc_id = doc_data["id"]

                    # Tags hinzufügen
                    doc_data["tags"] = StorageService.get_document_tags(doc_id)

                    # Chunk-Statistiken hinzufügen
                    doc_data["chunk_stats"] = StorageService.get_chunk_stats(doc_id)

                    metadata["documents"].append(doc_data)

                # Gesamtstatistiken
                cursor.execute("SELECT COUNT(*) as total FROM kb_documents")
                total_docs = cursor.fetchone()["total"]

                cursor.execute("SELECT COUNT(*) as total FROM kb_chunks")
                total_chunks = cursor.fetchone()["total"]

                cursor.execute("SELECT SUM(file_size) as total_size FROM kb_documents")
                total_size = cursor.fetchone()["total_size"] or 0

                metadata["statistics"] = {
                    "total_documents": total_docs,
                    "total_chunks": total_chunks,
                    "total_size_bytes": total_size,
                    "total_size_mb": round(total_size / (1024 * 1024), 2),
                }

                # Tag-Statistiken
                cursor.execute("""
                    SELECT tag, COUNT(*) as count 
                    FROM kb_tags 
                    GROUP BY tag 
                    ORDER BY count DESC
                """)

                metadata["tags"] = {
                    row["tag"]: row["count"] for row in cursor.fetchall()
                }

        except Exception as e:
            logger.error(f"Fehler beim Sammeln der Metadaten: {str(e)}")
            raise

        return metadata

    @classmethod
    def generate_readme(cls, export_info: Dict, metadata: Dict) -> str:
        """
        Generiert eine README-Datei für den Export

        Args:
            export_info: Export-Informationen
            metadata: Metadaten der Wissensbasis

        Returns:
            README-Inhalt als String
        """
        readme = f"""BookStack RAG Chatbot - Knowledge Base Backup
==============================================

Export date : {export_info['export_date']}
Exported by : {export_info['exported_by']}

Contents:
---------
- Document count    : {export_info['total_documents']}
- Successfully exported: {export_info['documents_exported']}
- Total size        : {metadata['statistics']['total_size_mb']} MB

Structure:
----------
- metadata.json   : Full metadata for every document
- documents/      : Folder with all document files
- export_info.json: Information about this export
- README.txt      : This file

Restore:
--------
1. Unpack the ZIP archive
2. Use the knowledge-base import function (scripts/kb_admin.py)
3. Point it at metadata.json and the documents/ folder

Notes:
------
- Document IDs are reassigned on restore
- Tags and metadata are preserved
- Chunk indexing may need to be rerun

Version: {export_info['export_version']}
"""
        return readme

    @classmethod
    def create_export_archive(
        cls, zipf, metadata: Dict, user_email: str = "admin"
    ) -> Dict:
        """
        Erstellt das Export-Archiv mit allen Dokumenten

        Args:
            zipf: ZipFile-Objekt
            metadata: Metadaten der Wissensbasis
            user_email: E-Mail des exportierenden Benutzers (widget-only: 'admin')

        Returns:
            Export-Info Dictionary
        """
        # Metadaten speichern
        metadata_json = json.dumps(metadata, indent=2, ensure_ascii=False)
        zipf.writestr("metadata.json", metadata_json)

        # Dokumente exportieren
        documents_exported = 0
        for doc_info in metadata["documents"]:
            doc_id = doc_info["id"]
            original_filename = doc_info["original_filename"]
            file_path = doc_info["file_path"]

            if os.path.exists(file_path):
                # Dokument mit originalem Namen in documents/ Ordner speichern
                archive_name = f"documents/{doc_id}_{original_filename}"
                zipf.write(file_path, archive_name)
                documents_exported += 1
            else:
                logger.warning(f"Datei nicht gefunden: {file_path}")

        # Export-Info erstellen
        export_info = {
            "export_date": datetime.now().isoformat(),
            "exported_by": user_email,
            "total_documents": len(metadata["documents"]),
            "documents_exported": documents_exported,
            "export_version": "1.0",
        }

        # Export-Info hinzufügen
        zipf.writestr("export_info.json", json.dumps(export_info, indent=2))

        # README hinzufügen
        readme_content = cls.generate_readme(export_info, metadata)
        zipf.writestr("README.txt", readme_content)

        return export_info
