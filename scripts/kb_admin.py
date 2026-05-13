#!/usr/bin/env python3
"""
Knowledge Base Administration CLI
Comprehensive command-line interface for managing external documents in the KB system
"""

import os
import sys
import argparse
import json
import time
from datetime import datetime
from typing import Dict, List, Any
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Import Knowledge Base services
try:
    from documents.knowledge_base.services.storage import StorageService
    from documents.knowledge_base.services.indexing import IndexingService
    from documents.knowledge_base.models import KnowledgeDocument  # noqa: F401
    from utils.database import get_db_connection
    from werkzeug.datastructures import FileStorage
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Ensure you're running this script from the correct directory.")
    sys.exit(1)

# CLI Configuration
CLI_VERSION = "0.1.1"
CLI_NAME = "kb_admin"

# Color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def colored_output(text: str, color: str) -> str:
    """Add color to terminal output"""
    return f"{color}{text}{Colors.ENDC}"

def print_success(message: str):
    """Print success message in green"""
    print(colored_output(f"✅ {message}", Colors.OKGREEN))

def print_error(message: str):
    """Print error message in red"""
    print(colored_output(f"❌ {message}", Colors.FAIL))

def print_warning(message: str):
    """Print warning message in yellow"""
    print(colored_output(f"⚠️  {message}", Colors.WARNING))

def print_info(message: str):
    """Print info message in blue"""
    print(colored_output(f"ℹ️  {message}", Colors.OKBLUE))

def print_header(message: str):
    """Print header message"""
    print(colored_output(f"\n{message}", Colors.HEADER + Colors.BOLD))
    print(colored_output("=" * len(message), Colors.HEADER))

class ProgressBar:
    """Simple progress bar for CLI operations"""

    def __init__(self, total: int, description: str = "Processing"):
        self.total = total
        self.current = 0
        self.description = description
        self.start_time = time.time()

    def update(self, increment: int = 1, item_name: str = ""):
        """Update progress bar"""
        self.current += increment
        percentage = (self.current / self.total) * 100
        elapsed = time.time() - self.start_time

        # Calculate ETA
        if self.current > 0:
            eta = (elapsed / self.current) * (self.total - self.current)
            eta_str = f"ETA: {eta:.1f}s"
        else:
            eta_str = "ETA: --"

        # Progress bar visualization
        bar_length = 30
        filled_length = int(bar_length * self.current // self.total)
        bar = '█' * filled_length + '-' * (bar_length - filled_length)

        # Display name
        display_item = f" | {item_name}" if item_name else ""

        print(f"\r{self.description}: |{bar}| {self.current}/{self.total} ({percentage:.1f}%) {eta_str}{display_item}", end='', flush=True)

        if self.current >= self.total:
            print()  # New line when complete

class CLIResponse:
    """Standardized CLI response format"""

    def __init__(self, success: bool = True, data: Any = None, message: str = "", errors: List[str] = None):
        self.success = success
        self.data = data
        self.message = message
        self.errors = errors or []
        self.timestamp = datetime.now().isoformat()
        self.duration_ms = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON output"""
        return {
            'success': self.success,
            'data': self.data,
            'message': self.message,
            'errors': self.errors,
            'metadata': {
                'timestamp': self.timestamp,
                'duration_ms': self.duration_ms,
                'version': CLI_VERSION
            }
        }

    def set_duration(self, start_time: float):
        """Set operation duration"""
        self.duration_ms = int((time.time() - start_time) * 1000)

def format_output(response: CLIResponse, format_type: str = 'table') -> str:
    """Format response for different output types"""
    if format_type == 'json':
        return json.dumps(response.to_dict(), indent=2, ensure_ascii=False)

    # Default table format
    output = []
    if not response.success:
        output.append(colored_output(f"❌ Error: {response.message}", Colors.FAIL))
        for error in response.errors:
            output.append(colored_output(f"   - {error}", Colors.FAIL))
    else:
        if response.message:
            output.append(colored_output(f"✅ {response.message}", Colors.OKGREEN))

    return '\n'.join(output)

def validate_database():
    """Validate database connection and KB tables"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Check if KB tables exist
            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name IN ('kb_documents', 'kb_chunks', 'kb_tags')
            """)

            tables = [row['name'] for row in cursor.fetchall()]
            required_tables = ['kb_documents', 'kb_chunks', 'kb_tags']
            missing_tables = set(required_tables) - set(tables)

            if missing_tables:
                print_error(f"Missing database tables: {', '.join(missing_tables)}")
                print_info("Run application setup first to create required tables.")
                return False

            return True

    except Exception as e:
        print_error(f"Database validation failed: {str(e)}")
        return False

def get_database_stats() -> Dict[str, Any]:
    """Get basic database statistics"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Document counts
            cursor.execute("SELECT COUNT(*) as total, SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) as active FROM kb_documents")
            doc_stats = cursor.fetchone()

            # Storage size
            cursor.execute("SELECT SUM(file_size) as total_size FROM kb_documents WHERE is_active = 1")
            size_stats = cursor.fetchone()

            # Chunk counts
            cursor.execute("SELECT COUNT(*) as total_chunks FROM kb_chunks")
            chunk_stats = cursor.fetchone()

            # Indexing status
            cursor.execute("""
                SELECT chunking_status, COUNT(*) as count
                FROM kb_documents
                GROUP BY chunking_status
            """)

            status_counts = {row['chunking_status']: row['count'] for row in cursor.fetchall()}

            return {
                'documents': {
                    'total': doc_stats['total'] or 0,
                    'active': doc_stats['active'] or 0,
                    'inactive': (doc_stats['total'] or 0) - (doc_stats['active'] or 0)
                },
                'storage': {
                    'total_size_bytes': size_stats['total_size'] or 0,
                    'total_size_mb': round((size_stats['total_size'] or 0) / 1024 / 1024, 2)
                },
                'chunks': {
                    'total': chunk_stats['total_chunks'] or 0
                },
                'indexing_status': status_counts
            }

    except Exception as e:
        return {'error': str(e)}

class KBAdmin:
    """Main Knowledge Base Administration class"""

    def __init__(self):
        self.start_time = time.time()

    # ============================================================================
    # DOCUMENTS COMMANDS
    # ============================================================================

    def documents_list(self, format_type: str = 'table', status: str = 'active', limit: int = 50) -> CLIResponse:
        """List documents in the knowledge base"""
        start_time = time.time()

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()

                # Build query based on status filter
                where_clause = ""
                params = []

                if status == 'active':
                    where_clause = "WHERE is_active = 1"
                elif status == 'inactive':
                    where_clause = "WHERE is_active = 0"
                # status == 'all' -> no where clause

                query = f"""
                    SELECT
                        id, title, original_filename, file_type, file_size,
                        chunking_status, chunk_count, uploaded_at, last_indexed
                    FROM kb_documents
                    {where_clause}
                    ORDER BY uploaded_at DESC
                    LIMIT ?
                """

                params.append(limit)
                cursor.execute(query, params)
                documents = [dict(row) for row in cursor.fetchall()]

                response = CLIResponse(
                    success=True,
                    data=documents,
                    message=f"Found {len(documents)} documents"
                )
                response.set_duration(start_time)
                return response

        except Exception as e:
            response = CLIResponse(
                success=False,
                message="Failed to list documents",
                errors=[str(e)]
            )
            response.set_duration(start_time)
            return response

    def documents_upload(self, file_path: str, title: str = "", tags: List[str] = None,
                        description: str = "") -> CLIResponse:
        """Upload a single document to the knowledge base"""
        start_time = time.time()

        try:
            # Validate file exists
            if not os.path.exists(file_path):
                return CLIResponse(
                    success=False,
                    message=f"File not found: {file_path}",
                    errors=[f"Path does not exist: {file_path}"]
                )

            # Validate file format
            supported_extensions = ['.pdf', '.docx', '.txt', '.md']
            file_ext = Path(file_path).suffix.lower()
            if file_ext not in supported_extensions:
                return CLIResponse(
                    success=False,
                    message=f"Unsupported file format: {file_ext}",
                    errors=[f"Supported formats: {', '.join(supported_extensions)}"]
                )

            # Create FileStorage object
            filename = os.path.basename(file_path)
            with open(file_path, 'rb') as f:
                file_storage = FileStorage(
                    stream=f,
                    filename=filename,
                    content_type='application/octet-stream'
                )

                # Upload file
                success, message, document = StorageService.save_file(
                    file=file_storage,
                    title=title or filename.rsplit('.', 1)[0],
                    description=description,
                    tags=tags or []
                )

                if success and document:
                    response = CLIResponse(
                        success=True,
                        data={
                            'id': document.id,
                            'title': document.title,
                            'filename': document.original_filename,
                            'size_bytes': document.file_size,
                            'hash': document.content_hash[:16]
                        },
                        message=f"Document uploaded successfully: {document.title}"
                    )
                else:
                    response = CLIResponse(
                        success=False,
                        message=message,
                        errors=[message] if not success else []
                    )

                response.set_duration(start_time)
                return response

        except Exception as e:
            response = CLIResponse(
                success=False,
                message="Upload failed",
                errors=[str(e)]
            )
            response.set_duration(start_time)
            return response

    def documents_show(self, doc_id: int, show_chunks: bool = False) -> CLIResponse:
        """Show detailed information about a document"""
        start_time = time.time()

        try:
            document = StorageService.get_document_by_id(doc_id)

            if not document:
                return CLIResponse(
                    success=False,
                    message=f"Document not found: {doc_id}",
                    errors=[f"No document with ID {doc_id}"]
                )

            # Get tags
            tags = StorageService.get_document_tags(doc_id)

            # Basic document info
            doc_data = {
                'id': document.id,
                'title': document.title,
                'original_filename': document.original_filename,
                'file_type': document.file_type,
                'file_size': document.file_size,
                'content_hash': document.content_hash,
                'uploaded_at': document.uploaded_at.isoformat() if document.uploaded_at else None,
                'tags': tags
            }

            # Add chunk information if requested
            if show_chunks:
                chunk_stats = StorageService.get_chunk_stats(doc_id)
                doc_data['chunks'] = chunk_stats

            response = CLIResponse(
                success=True,
                data=doc_data,
                message=f"Document details: {document.title}"
            )
            response.set_duration(start_time)
            return response

        except Exception as e:
            response = CLIResponse(
                success=False,
                message="Failed to retrieve document",
                errors=[str(e)]
            )
            response.set_duration(start_time)
            return response

    def documents_update(self, doc_id: int, title: str = None, tags: List[str] = None,
                        description: str = None) -> CLIResponse:
        """Update document metadata"""
        start_time = time.time()

        try:
            # Get current document
            document = StorageService.get_document_by_id(doc_id)
            if not document:
                return CLIResponse(
                    success=False,
                    message=f"Document not found: {doc_id}"
                )

            # Prepare update values (keep current values if not provided)
            update_title = title if title is not None else document.title
            update_description = description if description is not None else getattr(document, 'description', '')
            update_tags = tags if tags is not None else StorageService.get_document_tags(doc_id)

            # Update metadata
            success, message = StorageService.update_metadata(
                doc_id=doc_id,
                title=update_title,
                description=update_description,
                tags=update_tags
            )

            if success:
                response = CLIResponse(
                    success=True,
                    data={
                        'id': doc_id,
                        'title': update_title,
                        'tags': update_tags
                    },
                    message=f"Document updated: {update_title}"
                )
            else:
                response = CLIResponse(
                    success=False,
                    message=message,
                    errors=[message]
                )

            response.set_duration(start_time)
            return response

        except Exception as e:
            response = CLIResponse(
                success=False,
                message="Update failed",
                errors=[str(e)]
            )
            response.set_duration(start_time)
            return response

    def documents_delete(self, doc_id: int, confirm: bool = False) -> CLIResponse:
        """Delete a document from the knowledge base"""
        start_time = time.time()

        try:
            # Get document info first
            document = StorageService.get_document_by_id(doc_id)
            if not document:
                return CLIResponse(
                    success=False,
                    message=f"Document not found: {doc_id}"
                )

            if not confirm:
                return CLIResponse(
                    success=False,
                    message="Delete confirmation required",
                    errors=["Use --confirm flag to confirm deletion",
                           f"This will permanently delete: {document.title}"]
                )

            # Delete document
            success, message = StorageService.delete_file(doc_id)

            if success:
                response = CLIResponse(
                    success=True,
                    message=f"Document deleted: {document.title}"
                )
            else:
                response = CLIResponse(
                    success=False,
                    message=message,
                    errors=[message]
                )

            response.set_duration(start_time)
            return response

        except Exception as e:
            response = CLIResponse(
                success=False,
                message="Delete failed",
                errors=[str(e)]
            )
            response.set_duration(start_time)
            return response

    # ============================================================================
    # BULK COMMANDS
    # ============================================================================

    def bulk_upload(self, directory: str, recursive: bool = True, extensions: List[str] = None,
                   batch_size: int = 5, skip_existing: bool = False, tags: List[str] = None) -> CLIResponse:
        """Upload directory with documents"""
        start_time = time.time()

        try:
            if not os.path.exists(directory):
                return CLIResponse(
                    success=False,
                    message=f"Directory not found: {directory}"
                )

            # Default extensions
            if extensions is None:
                extensions = ['pdf', 'docx', 'txt', 'md']

            # Find files
            files_to_upload = []
            directory_path = Path(directory)

            if recursive:
                for ext in extensions:
                    files_to_upload.extend(directory_path.rglob(f'*.{ext}'))
            else:
                for ext in extensions:
                    files_to_upload.extend(directory_path.glob(f'*.{ext}'))

            if not files_to_upload:
                return CLIResponse(
                    success=True,
                    data={'uploaded': 0, 'skipped': 0, 'errors': 0},
                    message="No files found to upload"
                )

            # Process uploads
            progress = ProgressBar(len(files_to_upload), "Uploading files")
            results = {'uploaded': 0, 'skipped': 0, 'errors': 0, 'files': []}

            for file_path in files_to_upload:
                file_name = file_path.name
                progress.update(item_name=file_name)

                try:
                    # Check if file already exists (by filename or hash)
                    if skip_existing:
                        existing = self._check_file_exists(str(file_path))
                        if existing:
                            results['skipped'] += 1
                            results['files'].append({
                                'file': file_name,
                                'status': 'skipped',
                                'reason': 'Already exists'
                            })
                            continue

                    # Upload file
                    upload_result = self.documents_upload(
                        file_path=str(file_path),
                        title=file_path.stem,
                        tags=tags or [],
                        description=f"Uploaded from {directory}"
                    )

                    if upload_result.success:
                        results['uploaded'] += 1
                        results['files'].append({
                            'file': file_name,
                            'status': 'uploaded',
                            'id': upload_result.data['id']
                        })
                    else:
                        results['errors'] += 1
                        results['files'].append({
                            'file': file_name,
                            'status': 'error',
                            'reason': upload_result.message
                        })

                except Exception as e:
                    results['errors'] += 1
                    results['files'].append({
                        'file': file_name,
                        'status': 'error',
                        'reason': str(e)
                    })

            message = f"Upload complete: {results['uploaded']} uploaded, {results['skipped']} skipped, {results['errors']} errors"

            response = CLIResponse(
                success=results['errors'] == 0,
                data=results,
                message=message
            )
            response.set_duration(start_time)
            return response

        except Exception as e:
            response = CLIResponse(
                success=False,
                message="Bulk upload failed",
                errors=[str(e)]
            )
            response.set_duration(start_time)
            return response

    def bulk_reindex(self, force: bool = False, batch_size: int = 10) -> CLIResponse:
        """Reindex all documents in batches"""
        start_time = time.time()

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()

                # Get documents to reindex
                if force:
                    cursor.execute("SELECT id, title FROM kb_documents WHERE is_active = 1")
                else:
                    cursor.execute("""
                        SELECT id, title FROM kb_documents
                        WHERE is_active = 1 AND (chunking_status IS NULL OR chunking_status = 'failed')
                    """)

                documents = [{'id': row['id'], 'title': row['title']} for row in cursor.fetchall()]

                if not documents:
                    return CLIResponse(
                        success=True,
                        data={'reindexed': 0, 'errors': 0},
                        message="No documents need reindexing"
                    )

                progress = ProgressBar(len(documents), "Reindexing documents")
                results = {'reindexed': 0, 'errors': 0, 'details': []}

                # Process in batches
                for i, doc in enumerate(documents):
                    progress.update(item_name=doc['title'][:30])

                    try:
                        # Trigger reindexing
                        success, _ = IndexingService.index_document(doc['id'])

                        if success:
                            results['reindexed'] += 1
                            results['details'].append({
                                'id': doc['id'],
                                'title': doc['title'],
                                'status': 'reindexed'
                            })
                        else:
                            results['errors'] += 1
                            results['details'].append({
                                'id': doc['id'],
                                'title': doc['title'],
                                'status': 'failed'
                            })

                    except Exception as e:
                        results['errors'] += 1
                        results['details'].append({
                            'id': doc['id'],
                            'title': doc['title'],
                            'status': 'error',
                            'reason': str(e)
                        })

                    # Small delay between batches
                    if (i + 1) % batch_size == 0:
                        time.sleep(0.1)

                message = f"Reindexing complete: {results['reindexed']} processed, {results['errors']} errors"

                response = CLIResponse(
                    success=results['errors'] == 0,
                    data=results,
                    message=message
                )
                response.set_duration(start_time)
                return response

        except Exception as e:
            response = CLIResponse(
                success=False,
                message="Bulk reindexing failed",
                errors=[str(e)]
            )
            response.set_duration(start_time)
            return response

    def bulk_cleanup(self, dry_run: bool = True, older_than_days: int = 30) -> CLIResponse:
        """Clean up orphaned chunks and outdated data"""
        start_time = time.time()

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()

                cleanup_results = {
                    'orphaned_chunks': 0,
                    'old_deleted_docs': 0,
                    'stale_sessions': 0,
                    'details': []
                }

                # Find orphaned chunks
                cursor.execute("""
                    SELECT COUNT(*) as count FROM kb_chunks
                    WHERE doc_id NOT IN (SELECT id FROM kb_documents WHERE is_active = 1)
                """)
                orphaned_chunks = cursor.fetchone()['count']

                if orphaned_chunks > 0:
                    cleanup_results['orphaned_chunks'] = orphaned_chunks
                    cleanup_results['details'].append(f"Found {orphaned_chunks} orphaned chunks")

                    if not dry_run:
                        cursor.execute("""
                            DELETE FROM kb_chunks
                            WHERE doc_id NOT IN (SELECT id FROM kb_documents WHERE is_active = 1)
                        """)

                # Find old deleted documents (soft-deleted)
                cursor.execute(f"""
                    SELECT COUNT(*) as count FROM kb_documents
                    WHERE is_active = 0 AND uploaded_at < datetime('now', '-{older_than_days} days')
                """)
                old_deleted = cursor.fetchone()['count']

                if old_deleted > 0:
                    cleanup_results['old_deleted_docs'] = old_deleted
                    cleanup_results['details'].append(f"Found {old_deleted} old deleted documents")

                    if not dry_run:
                        cursor.execute(f"""
                            DELETE FROM kb_documents
                            WHERE is_active = 0 AND uploaded_at < datetime('now', '-{older_than_days} days')
                        """)

                # Clean up stale widget sessions (if widget_logs table exists)
                try:
                    cursor.execute("""
                        SELECT COUNT(*) as count FROM widget_logs
                        WHERE created_at < datetime('now', '-1 day')
                    """)
                    stale_sessions = cursor.fetchone()['count']

                    if stale_sessions > 0:
                        cleanup_results['stale_sessions'] = stale_sessions
                        cleanup_results['details'].append(f"Found {stale_sessions} old widget sessions")

                        if not dry_run:
                            cursor.execute("""
                                DELETE FROM widget_logs
                                WHERE created_at < datetime('now', '-1 day')
                            """)
                except Exception:
                    # widget_logs table doesn't exist - skip
                    pass

                if not dry_run:
                    conn.commit()

                action_text = "Would clean up" if dry_run else "Cleaned up"
                total_items = sum([cleanup_results['orphaned_chunks'],
                                 cleanup_results['old_deleted_docs'],
                                 cleanup_results['stale_sessions']])

                message = f"{action_text}: {total_items} items"

                response = CLIResponse(
                    success=True,
                    data=cleanup_results,
                    message=message
                )
                response.set_duration(start_time)
                return response

        except Exception as e:
            response = CLIResponse(
                success=False,
                message="Cleanup operation failed",
                errors=[str(e)]
            )
            response.set_duration(start_time)
            return response

    def _check_file_exists(self, file_path: str) -> bool:
        """Check if file already exists in KB by filename or hash"""
        try:
            import hashlib

            # Calculate file hash
            with open(file_path, 'rb') as f:
                file_hash = hashlib.md5(f.read()).hexdigest()

            filename = os.path.basename(file_path)

            with get_db_connection() as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT COUNT(*) as count FROM kb_documents
                    WHERE is_active = 1 AND (original_filename = ? OR content_hash = ?)
                """, (filename, file_hash))

                return cursor.fetchone()['count'] > 0

        except Exception:
            return False

    # ============================================================================
    # INDEX COMMANDS
    # ============================================================================

    def index_status(self) -> CLIResponse:
        """Check indexing status across all documents"""
        start_time = time.time()

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()

                # Overall statistics
                cursor.execute("""
                    SELECT
                        COUNT(*) as total_docs,
                        SUM(CASE WHEN chunking_status = 'completed' THEN 1 ELSE 0 END) as indexed,
                        SUM(CASE WHEN chunking_status = 'processing' THEN 1 ELSE 0 END) as processing,
                        SUM(CASE WHEN chunking_status = 'failed' THEN 1 ELSE 0 END) as failed,
                        SUM(CASE WHEN chunking_status IS NULL THEN 1 ELSE 0 END) as pending
                    FROM kb_documents
                    WHERE is_active = 1
                """)

                stats = cursor.fetchone()

                # Recent indexing activity
                cursor.execute("""
                    SELECT id, title, chunking_status, last_indexed, chunk_count
                    FROM kb_documents
                    WHERE is_active = 1 AND last_indexed IS NOT NULL
                    ORDER BY last_indexed DESC
                    LIMIT 10
                """)

                recent_activity = [dict(row) for row in cursor.fetchall()]

                # FTS index health
                cursor.execute("SELECT COUNT(*) as fts_entries FROM kb_chunks_fts")
                fts_stats = cursor.fetchone()

                # Problem documents
                cursor.execute("""
                    SELECT id, title, chunking_status
                    FROM kb_documents
                    WHERE is_active = 1 AND chunking_status IN ('failed', 'processing')
                    ORDER BY last_indexed DESC
                    LIMIT 10
                """)

                problem_docs = [dict(row) for row in cursor.fetchall()]

                index_data = {
                    'overview': {
                        'total_documents': stats['total_docs'],
                        'indexed': stats['indexed'],
                        'processing': stats['processing'],
                        'failed': stats['failed'],
                        'pending': stats['pending'],
                        'fts_entries': fts_stats['fts_entries']
                    },
                    'recent_activity': recent_activity,
                    'problem_documents': problem_docs
                }

                response = CLIResponse(
                    success=True,
                    data=index_data,
                    message=f"Index status: {stats['indexed']}/{stats['total_docs']} documents indexed"
                )
                response.set_duration(start_time)
                return response

        except Exception as e:
            response = CLIResponse(
                success=False,
                message="Failed to get index status",
                errors=[str(e)]
            )
            response.set_duration(start_time)
            return response

    def index_rebuild(self, document_id: int = None, force: bool = False) -> CLIResponse:
        """Rebuild index for specific document or all documents"""
        start_time = time.time()

        try:
            if document_id:
                # Rebuild single document
                document = StorageService.get_document_by_id(document_id)
                if not document:
                    return CLIResponse(
                        success=False,
                        message=f"Document not found: {document_id}"
                    )

                # Clear existing chunks
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM kb_chunks WHERE doc_id = ?", (document_id,))
                    cursor.execute("UPDATE kb_documents SET chunking_status = NULL, chunk_count = 0 WHERE id = ?", (document_id,))
                    conn.commit()

                # Trigger reindexing
                success, _ = IndexingService.index_document(document_id)

                if success:
                    response = CLIResponse(
                        success=True,
                        data={'document_id': document_id, 'title': document.title},
                        message=f"Index rebuilt for: {document.title}"
                    )
                else:
                    response = CLIResponse(
                        success=False,
                        message=f"Failed to rebuild index for document {document_id}"
                    )

            else:
                # Rebuild all documents
                with get_db_connection() as conn:
                    cursor = conn.cursor()

                    if force:
                        # Clear all chunks and reset status
                        cursor.execute("DELETE FROM kb_chunks")
                        cursor.execute("UPDATE kb_documents SET chunking_status = NULL, chunk_count = 0 WHERE is_active = 1")
                        cursor.execute("DELETE FROM kb_chunks_fts")
                        conn.commit()

                        cursor.execute("SELECT COUNT(*) as count FROM kb_documents WHERE is_active = 1")
                        total_docs = cursor.fetchone()['count']

                        response = CLIResponse(
                            success=True,
                            data={'cleared_documents': total_docs, 'reindexing_triggered': True},
                            message=f"Full index rebuild initiated for {total_docs} documents"
                        )
                    else:
                        # Only rebuild failed/pending documents
                        cursor.execute("""
                            UPDATE kb_documents SET chunking_status = NULL
                            WHERE is_active = 1 AND chunking_status IN ('failed', 'processing')
                        """)
                        affected = cursor.rowcount
                        conn.commit()

                        response = CLIResponse(
                            success=True,
                            data={'reset_documents': affected, 'reindexing_triggered': True},
                            message=f"Index rebuild initiated for {affected} failed documents"
                        )

            response.set_duration(start_time)
            return response

        except Exception as e:
            response = CLIResponse(
                success=False,
                message="Index rebuild failed",
                errors=[str(e)]
            )
            response.set_duration(start_time)
            return response

    def index_optimize(self) -> CLIResponse:
        """Optimize FTS indexes and database performance"""
        start_time = time.time()

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()

                optimization_results = []

                # Rebuild FTS indexes
                cursor.execute("INSERT INTO kb_chunks_fts(kb_chunks_fts) VALUES('rebuild')")
                optimization_results.append("FTS index rebuilt")

                # Analyze and optimize tables
                for table in ['kb_documents', 'kb_chunks', 'kb_chunks_fts']:
                    cursor.execute(f"ANALYZE {table}")

                optimization_results.append("Table statistics updated")

                # Vacuum to reclaim space
                cursor.execute("VACUUM")
                optimization_results.append("Database vacuumed")

                # Update SQLite optimization settings
                cursor.execute("PRAGMA optimize")
                optimization_results.append("SQLite optimization applied")

                conn.commit()

                response = CLIResponse(
                    success=True,
                    data={'optimizations': optimization_results},
                    message=f"Index optimization complete: {len(optimization_results)} operations"
                )
                response.set_duration(start_time)
                return response

        except Exception as e:
            response = CLIResponse(
                success=False,
                message="Index optimization failed",
                errors=[str(e)]
            )
            response.set_duration(start_time)
            return response

    # ============================================================================
    # STATS COMMANDS
    # ============================================================================

    def stats_overview(self) -> CLIResponse:
        """Get comprehensive system statistics"""
        start_time = time.time()

        try:
            db_stats = get_database_stats()

            if 'error' in db_stats:
                return CLIResponse(
                    success=False,
                    message="Failed to retrieve statistics",
                    errors=[db_stats['error']]
                )

            # Additional performance metrics
            with get_db_connection() as conn:
                cursor = conn.cursor()

                # Response time analysis (last 24 hours from widget_logs if available)
                try:
                    cursor.execute("""
                        SELECT
                            AVG(response_time) as avg_response,
                            MIN(response_time) as min_response,
                            MAX(response_time) as max_response,
                            COUNT(*) as total_queries
                        FROM widget_logs
                        WHERE created_at > datetime('now', '-24 hours')
                    """)
                    performance = dict(cursor.fetchone())
                except Exception:
                    performance = {'avg_response': 0, 'min_response': 0, 'max_response': 0, 'total_queries': 0}

                # Top search terms (if available)
                try:
                    cursor.execute("""
                        SELECT message as query, COUNT(*) as frequency
                        FROM widget_logs
                        WHERE created_at > datetime('now', '-7 days')
                        GROUP BY message
                        ORDER BY frequency DESC
                        LIMIT 10
                    """)
                    top_queries = [dict(row) for row in cursor.fetchall()]
                except Exception:
                    top_queries = []

                # Storage distribution by file type
                cursor.execute("""
                    SELECT
                        file_type,
                        COUNT(*) as count,
                        SUM(file_size) as total_size,
                        AVG(file_size) as avg_size
                    FROM kb_documents
                    WHERE is_active = 1
                    GROUP BY file_type
                    ORDER BY count DESC
                """)
                file_type_stats = [dict(row) for row in cursor.fetchall()]

            # Combine all stats
            comprehensive_stats = {
                'system_overview': db_stats,
                'performance': {
                    'avg_response_time_ms': round(performance['avg_response'] or 0, 2),
                    'min_response_time_ms': performance['min_response'] or 0,
                    'max_response_time_ms': performance['max_response'] or 0,
                    'queries_24h': performance['total_queries'] or 0
                },
                'content_analysis': {
                    'file_type_distribution': file_type_stats,
                    'top_search_queries': top_queries
                },
                'health_indicators': self._calculate_health_indicators(db_stats)
            }

            response = CLIResponse(
                success=True,
                data=comprehensive_stats,
                message=f"System statistics: {db_stats['documents']['active']} active documents, {db_stats['chunks']['total']} chunks"
            )
            response.set_duration(start_time)
            return response

        except Exception as e:
            response = CLIResponse(
                success=False,
                message="Failed to generate statistics",
                errors=[str(e)]
            )
            response.set_duration(start_time)
            return response

    def stats_usage(self, days: int = 30) -> CLIResponse:
        """Get usage statistics for specified time period"""
        start_time = time.time()

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()

                # Usage metrics
                usage_stats = {}

                # Daily query counts
                try:
                    cursor.execute(f"""
                        SELECT
                            date(created_at) as query_date,
                            COUNT(*) as query_count,
                            COUNT(DISTINCT session_id) as unique_sessions
                        FROM widget_logs
                        WHERE created_at > datetime('now', '-{days} days')
                        GROUP BY date(created_at)
                        ORDER BY query_date DESC
                        LIMIT 30
                    """)
                    daily_usage = [dict(row) for row in cursor.fetchall()]
                    usage_stats['daily_usage'] = daily_usage
                except Exception:
                    usage_stats['daily_usage'] = []

                # Session statistics
                try:
                    cursor.execute(f"""
                        SELECT
                            session_id,
                            COUNT(*) as messages_per_session,
                            MIN(created_at) as session_start,
                            MAX(created_at) as session_end
                        FROM widget_logs
                        WHERE created_at > datetime('now', '-{days} days')
                        GROUP BY session_id
                        ORDER BY messages_per_session DESC
                        LIMIT 10
                    """)
                    session_stats = [dict(row) for row in cursor.fetchall()]

                    if session_stats:
                        avg_messages = sum(s['messages_per_session'] for s in session_stats) / len(session_stats)
                        usage_stats['session_analysis'] = {
                            'total_sessions': len(session_stats),
                            'avg_messages_per_session': round(avg_messages, 2),
                            'top_sessions': session_stats[:5]
                        }
                    else:
                        usage_stats['session_analysis'] = {'total_sessions': 0, 'avg_messages_per_session': 0}
                except Exception:
                    usage_stats['session_analysis'] = {'total_sessions': 0, 'avg_messages_per_session': 0}

                # Document access patterns
                cursor.execute(f"""
                    SELECT
                        kb_documents.title,
                        kb_documents.file_type,
                        COUNT(*) as access_count
                    FROM widget_logs
                    LEFT JOIN kb_chunks ON widget_logs.question LIKE '%' || kb_chunks.chunk_text || '%'
                    LEFT JOIN kb_documents ON kb_chunks.doc_id = kb_documents.id
                    WHERE widget_logs.created_at > datetime('now', '-{days} days')
                      AND kb_documents.id IS NOT NULL
                    GROUP BY kb_documents.id
                    ORDER BY access_count DESC
                    LIMIT 10
                """)
                document_access = [dict(row) for row in cursor.fetchall()]
                usage_stats['document_popularity'] = document_access

            response = CLIResponse(
                success=True,
                data=usage_stats,
                message=f"Usage statistics for last {days} days"
            )
            response.set_duration(start_time)
            return response

        except Exception as e:
            response = CLIResponse(
                success=False,
                message="Failed to retrieve usage statistics",
                errors=[str(e)]
            )
            response.set_duration(start_time)
            return response

    def stats_performance(self) -> CLIResponse:
        """Get detailed performance metrics"""
        start_time = time.time()

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()

                performance_data = {}

                # Database size and growth
                cursor.execute("SELECT page_count * page_size as size FROM pragma_page_count(), pragma_page_size()")
                db_size = cursor.fetchone()['size']

                # Index efficiency
                cursor.execute("SELECT COUNT(*) as total_chunks FROM kb_chunks")
                total_chunks = cursor.fetchone()['total_chunks']

                cursor.execute("SELECT COUNT(*) as fts_entries FROM kb_chunks_fts")
                fts_entries = cursor.fetchone()['fts_entries']

                # Query performance (if available)
                try:
                    cursor.execute("""
                        SELECT
                            AVG(response_time) as avg_response,
                            PERCENTILE(response_time, 50) as median_response,
                            PERCENTILE(response_time, 95) as p95_response,
                            COUNT(*) as sample_size
                        FROM widget_logs
                        WHERE created_at > datetime('now', '-24 hours') AND response_time IS NOT NULL
                    """)
                    query_perf = dict(cursor.fetchone() or {})
                except Exception:
                    query_perf = {}

                # Chunking efficiency
                cursor.execute("""
                    SELECT
                        AVG(LENGTH(content)) as avg_chunk_size,
                        MIN(LENGTH(content)) as min_chunk_size,
                        MAX(LENGTH(content)) as max_chunk_size,
                        COUNT(*) as total_chunks
                    FROM kb_chunks
                """)
                chunk_stats = dict(cursor.fetchone() or {})

                performance_data = {
                    'database': {
                        'size_bytes': db_size,
                        'size_mb': round(db_size / 1024 / 1024, 2)
                    },
                    'indexing': {
                        'total_chunks': total_chunks,
                        'fts_entries': fts_entries,
                        'index_ratio': round(fts_entries / max(total_chunks, 1), 2)
                    },
                    'query_performance': query_perf,
                    'chunking_metrics': chunk_stats
                }

            response = CLIResponse(
                success=True,
                data=performance_data,
                message=f"Performance metrics: {performance_data['database']['size_mb']} MB database"
            )
            response.set_duration(start_time)
            return response

        except Exception as e:
            response = CLIResponse(
                success=False,
                message="Failed to retrieve performance metrics",
                errors=[str(e)]
            )
            response.set_duration(start_time)
            return response

    def _calculate_health_indicators(self, db_stats: Dict[str, Any]) -> Dict[str, str]:
        """Calculate system health indicators"""
        indicators = {}

        # Document health
        total_docs = db_stats['documents']['total']
        active_docs = db_stats['documents']['active']

        if total_docs == 0:
            indicators['document_health'] = 'EMPTY'
        elif active_docs / total_docs > 0.8:
            indicators['document_health'] = 'HEALTHY'
        elif active_docs / total_docs > 0.5:
            indicators['document_health'] = 'WARNING'
        else:
            indicators['document_health'] = 'CRITICAL'

        # Indexing health
        indexing_status = db_stats.get('indexing_status', {})
        completed = indexing_status.get('completed', 0)
        failed = indexing_status.get('failed', 0)

        if completed + failed == 0:
            indicators['indexing_health'] = 'PENDING'
        elif failed / max(completed + failed, 1) > 0.2:
            indicators['indexing_health'] = 'CRITICAL'
        elif failed > 0:
            indicators['indexing_health'] = 'WARNING'
        else:
            indicators['indexing_health'] = 'HEALTHY'

        # Storage health
        total_size_mb = db_stats['storage']['total_size_mb']

        if total_size_mb > 1000:  # > 1GB
            indicators['storage_health'] = 'LARGE'
        elif total_size_mb > 100:  # > 100MB
            indicators['storage_health'] = 'MODERATE'
        else:
            indicators['storage_health'] = 'LIGHT'

        return indicators

    # ============================================================================
    # MAINTENANCE COMMANDS
    # ============================================================================

    def maintenance_health_check(self) -> CLIResponse:
        """Comprehensive system health check"""
        start_time = time.time()

        try:
            health_results = {
                'database_connectivity': False,
                'table_integrity': False,
                'index_health': False,
                'storage_access': False,
                'service_dependencies': False,
                'issues_found': [],
                'recommendations': []
            }

            # Database connectivity
            try:
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT 1")
                    health_results['database_connectivity'] = True
            except Exception as e:
                health_results['issues_found'].append(f"Database connectivity: {str(e)}")

            # Table integrity
            try:
                with get_db_connection() as conn:
                    cursor = conn.cursor()

                    required_tables = ['kb_documents', 'kb_chunks', 'kb_chunks_fts']
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    existing_tables = [row['name'] for row in cursor.fetchall()]

                    missing_tables = set(required_tables) - set(existing_tables)

                    if not missing_tables:
                        health_results['table_integrity'] = True
                    else:
                        health_results['issues_found'].append(f"Missing tables: {', '.join(missing_tables)}")
                        health_results['recommendations'].append("Run database setup/migration")

            except Exception as e:
                health_results['issues_found'].append(f"Table integrity check failed: {str(e)}")

            # Index health
            try:
                with get_db_connection() as conn:
                    cursor = conn.cursor()

                    cursor.execute("SELECT COUNT(*) as chunks FROM kb_chunks")
                    chunk_count = cursor.fetchone()['chunks']

                    cursor.execute("SELECT COUNT(*) as fts_entries FROM kb_chunks_fts")
                    fts_count = cursor.fetchone()['fts_entries']

                    if chunk_count == 0:
                        health_results['index_health'] = True  # No chunks yet is OK
                    elif abs(chunk_count - fts_count) / chunk_count < 0.1:  # Within 10%
                        health_results['index_health'] = True
                    else:
                        health_results['issues_found'].append(f"Index mismatch: {chunk_count} chunks vs {fts_count} FTS entries")
                        health_results['recommendations'].append("Run index rebuild")

            except Exception as e:
                health_results['issues_found'].append(f"Index health check failed: {str(e)}")

            # Storage access
            try:
                # Try to access storage directory
                storage_path = Path("data")  # Adjust based on actual storage path
                if storage_path.exists() and storage_path.is_dir():
                    health_results['storage_access'] = True
                else:
                    health_results['issues_found'].append("Storage directory not accessible")
                    health_results['recommendations'].append("Check storage directory permissions")

            except Exception as e:
                health_results['issues_found'].append(f"Storage access check failed: {str(e)}")

            # Service dependencies (basic check)
            try:
                # Check if required modules are importable
                required_modules = ['documents.knowledge_base.services.storage',
                                  'documents.knowledge_base.services.indexing']
                for module in required_modules:
                    __import__(module)
                health_results['service_dependencies'] = True

            except Exception as e:
                health_results['issues_found'].append(f"Service dependency check failed: {str(e)}")
                health_results['recommendations'].append("Check application dependencies")

            # Overall health assessment
            checks_passed = sum([
                health_results['database_connectivity'],
                health_results['table_integrity'],
                health_results['index_health'],
                health_results['storage_access'],
                health_results['service_dependencies']
            ])

            health_results['overall_status'] = {
                'checks_passed': checks_passed,
                'checks_total': 5,
                'health_score': round(checks_passed / 5 * 100, 1)
            }

            is_healthy = len(health_results['issues_found']) == 0
            message = f"Health check complete: {health_results['overall_status']['health_score']}% ({checks_passed}/5 checks passed)"

            response = CLIResponse(
                success=is_healthy,
                data=health_results,
                message=message
            )
            response.set_duration(start_time)
            return response

        except Exception as e:
            response = CLIResponse(
                success=False,
                message="Health check failed",
                errors=[str(e)]
            )
            response.set_duration(start_time)
            return response

def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        prog=CLI_NAME,
        description="Knowledge Base Administration CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  {CLI_NAME} documents list --format json
  {CLI_NAME} documents upload --file manual.pdf --title "User Manual" --tags manual,docs
  {CLI_NAME} documents show --id 42 --chunks
  {CLI_NAME} bulk upload --directory /docs --tags imported
  {CLI_NAME} stats overview
        """
    )

    parser.add_argument('--version', action='version', version=f'{CLI_NAME} {CLI_VERSION}')
    parser.add_argument('--format', choices=['table', 'json'], default='table',
                       help='Output format (default: table)')

    # Subcommands
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # ============================================================================
    # DOCUMENTS SUBCOMMANDS
    # ============================================================================
    documents_parser = subparsers.add_parser('documents', help='Document management')
    docs_subparsers = documents_parser.add_subparsers(dest='docs_action', help='Document actions')

    # documents list
    docs_list = docs_subparsers.add_parser('list', help='List documents')
    docs_list.add_argument('--status', choices=['active', 'inactive', 'all'], default='active',
                          help='Filter by status (default: active)')
    docs_list.add_argument('--limit', type=int, default=50,
                          help='Maximum number of results (default: 50)')

    # documents upload
    docs_upload = docs_subparsers.add_parser('upload', help='Upload document')
    docs_upload.add_argument('--file', required=True, help='File path to upload')
    docs_upload.add_argument('--title', help='Document title (default: filename)')
    docs_upload.add_argument('--tags', help='Comma-separated tags')
    docs_upload.add_argument('--description', help='Document description')

    # documents show
    docs_show = docs_subparsers.add_parser('show', help='Show document details')
    docs_show.add_argument('--id', type=int, required=True, help='Document ID')
    docs_show.add_argument('--chunks', action='store_true', help='Include chunk information')

    # documents update
    docs_update = docs_subparsers.add_parser('update', help='Update document metadata')
    docs_update.add_argument('--id', type=int, required=True, help='Document ID')
    docs_update.add_argument('--title', help='New title')
    docs_update.add_argument('--tags', help='New tags (comma-separated)')
    docs_update.add_argument('--description', help='New description')

    # documents delete
    docs_delete = docs_subparsers.add_parser('delete', help='Delete document')
    docs_delete.add_argument('--id', type=int, required=True, help='Document ID')
    docs_delete.add_argument('--confirm', action='store_true', help='Confirm deletion')

    # ============================================================================
    # BULK SUBCOMMANDS
    # ============================================================================
    bulk_parser = subparsers.add_parser('bulk', help='Bulk operations')
    bulk_subparsers = bulk_parser.add_subparsers(dest='bulk_action', help='Bulk actions')

    # bulk upload
    bulk_upload = bulk_subparsers.add_parser('upload', help='Upload directory')
    bulk_upload.add_argument('--directory', required=True, help='Directory to upload')
    bulk_upload.add_argument('--recursive', action='store_true', help='Include subdirectories')
    bulk_upload.add_argument('--extensions', default='pdf,docx,txt,md', help='File extensions (comma-separated)')
    bulk_upload.add_argument('--batch-size', type=int, default=5, help='Parallel uploads')
    bulk_upload.add_argument('--skip-existing', action='store_true', help='Skip existing files')
    bulk_upload.add_argument('--tags', help='Tags for all uploaded files')

    # bulk reindex
    bulk_reindex = bulk_subparsers.add_parser('reindex', help='Reindex documents')
    bulk_reindex.add_argument('--force', action='store_true', help='Force reindex all documents')
    bulk_reindex.add_argument('--batch-size', type=int, default=10, help='Batch size')

    # bulk cleanup
    bulk_cleanup = bulk_subparsers.add_parser('cleanup', help='Clean up orphaned data')
    bulk_cleanup.add_argument('--dry-run', action='store_true', help='Show what would be deleted')
    bulk_cleanup.add_argument('--older-than', type=int, default=30, help='Delete items older than N days')

    # ============================================================================
    # INDEX SUBCOMMANDS
    # ============================================================================
    index_parser = subparsers.add_parser('index', help='Index management')
    index_subparsers = index_parser.add_subparsers(dest='index_action', help='Index actions')

    # index status
    index_subparsers.add_parser('status', help='Check index status')

    # index rebuild
    index_rebuild = index_subparsers.add_parser('rebuild', help='Rebuild indexes')
    index_rebuild.add_argument('--document-id', type=int, help='Rebuild specific document')
    index_rebuild.add_argument('--force', action='store_true', help='Force full rebuild')

    # index optimize
    index_subparsers.add_parser('optimize', help='Optimize indexes')

    # ============================================================================
    # STATS SUBCOMMANDS
    # ============================================================================
    stats_parser = subparsers.add_parser('stats', help='Statistics and monitoring')
    stats_subparsers = stats_parser.add_subparsers(dest='stats_action', help='Statistics actions')

    # stats overview
    stats_subparsers.add_parser('overview', help='System overview')

    # stats usage
    stats_usage = stats_subparsers.add_parser('usage', help='Usage statistics')
    stats_usage.add_argument('--days', type=int, default=30, help='Days to analyze')

    # stats performance
    stats_subparsers.add_parser('performance', help='Performance metrics')

    # ============================================================================
    # MAINTENANCE SUBCOMMANDS
    # ============================================================================
    maintenance_parser = subparsers.add_parser('maintenance', help='System maintenance')
    maintenance_subparsers = maintenance_parser.add_subparsers(dest='maintenance_action', help='Maintenance actions')

    # maintenance health-check
    maintenance_subparsers.add_parser('health-check', help='System health check')

    # Parse arguments
    args = parser.parse_args()

    # Validate database before proceeding
    if not validate_database():
        sys.exit(1)

    # Initialize admin interface
    admin = KBAdmin()

    # Route commands
    try:
        if args.command == 'documents':
            if args.docs_action == 'list':
                response = admin.documents_list(
                    format_type=args.format,
                    status=args.status,
                    limit=args.limit
                )
            elif args.docs_action == 'upload':
                tags = args.tags.split(',') if args.tags else []
                response = admin.documents_upload(
                    file_path=args.file,
                    title=args.title,
                    tags=tags,
                    description=args.description
                )
            elif args.docs_action == 'show':
                response = admin.documents_show(
                    doc_id=args.id,
                    show_chunks=args.chunks
                )
            elif args.docs_action == 'update':
                tags = args.tags.split(',') if args.tags else None
                response = admin.documents_update(
                    doc_id=args.id,
                    title=args.title,
                    tags=tags,
                    description=args.description
                )
            elif args.docs_action == 'delete':
                response = admin.documents_delete(
                    doc_id=args.id,
                    confirm=args.confirm
                )
            else:
                parser.error(f"Unknown documents action: {args.docs_action}")

        elif args.command == 'bulk':
            if args.bulk_action == 'upload':
                tags = args.tags.split(',') if args.tags else []
                extensions = args.extensions.split(',')
                response = admin.bulk_upload(
                    directory=args.directory,
                    recursive=args.recursive,
                    extensions=extensions,
                    batch_size=args.batch_size,
                    skip_existing=args.skip_existing,
                    tags=tags
                )
            elif args.bulk_action == 'reindex':
                response = admin.bulk_reindex(
                    force=args.force,
                    batch_size=args.batch_size
                )
            elif args.bulk_action == 'cleanup':
                response = admin.bulk_cleanup(
                    dry_run=args.dry_run,
                    older_than_days=args.older_than
                )
            else:
                parser.error(f"Unknown bulk action: {args.bulk_action}")

        elif args.command == 'index':
            if args.index_action == 'status':
                response = admin.index_status()
            elif args.index_action == 'rebuild':
                response = admin.index_rebuild(
                    document_id=args.document_id,
                    force=args.force
                )
            elif args.index_action == 'optimize':
                response = admin.index_optimize()
            else:
                parser.error(f"Unknown index action: {args.index_action}")

        elif args.command == 'stats':
            if args.stats_action == 'overview':
                response = admin.stats_overview()
            elif args.stats_action == 'usage':
                response = admin.stats_usage(days=args.days)
            elif args.stats_action == 'performance':
                response = admin.stats_performance()
            else:
                parser.error(f"Unknown stats action: {args.stats_action}")

        elif args.command == 'maintenance':
            if args.maintenance_action == 'health-check':
                response = admin.maintenance_health_check()
            else:
                parser.error(f"Unknown maintenance action: {args.maintenance_action}")

        else:
            # Show help if no command provided
            parser.print_help()
            sys.exit(0)

        # Output response
        if args.format == 'json':
            print(json.dumps(response.to_dict(), indent=2, ensure_ascii=False))
        else:
            # Table format with colored output
            if response.success:
                if response.message:
                    print_success(response.message)

                # Display data in table format
                if response.data:
                    if args.command == 'documents' and args.docs_action == 'list':
                        # Table for document list
                        documents = response.data
                        if documents:
                            print_header("Documents")
                            print(f"{'ID':<4} {'Title':<30} {'Type':<6} {'Size':<10} {'Status':<12} {'Uploaded':<12}")
                            print("-" * 80)

                            for doc in documents:
                                size_mb = round(doc['file_size'] / 1024 / 1024, 2) if doc['file_size'] else 0
                                status = doc['chunking_status'] or 'pending'
                                uploaded = doc['uploaded_at'][:10] if doc['uploaded_at'] else 'N/A'

                                title = doc['title'][:28] + '...' if len(doc['title']) > 30 else doc['title']

                                print(f"{doc['id']:<4} {title:<30} {doc['file_type']:<6} {size_mb:<10.2f} {status:<12} {uploaded:<12}")

                    elif args.command == 'documents' and args.docs_action == 'show':
                        # Detailed document view
                        doc = response.data
                        print_header(f"Document Details: {doc['title']}")
                        print(f"ID: {doc['id']}")
                        print(f"Original Filename: {doc['original_filename']}")
                        print(f"File Type: {doc['file_type']}")
                        print(f"File Size: {round(doc['file_size'] / 1024 / 1024, 2)} MB")
                        print(f"Content Hash: {doc['content_hash'][:16]}...")
                        print(f"Uploaded: {doc['uploaded_at']}")

                        if doc['tags']:
                            print(f"Tags: {', '.join(doc['tags'])}")

                        if 'chunks' in doc and doc['chunks']:
                            print_header("Chunk Information")
                            chunks = doc['chunks']
                            print(f"Total Chunks: {chunks.get('total_chunks', 0)}")
                            print(f"Average Words per Chunk: {chunks.get('avg_words', 0)}")

                    elif args.command == 'bulk':
                        # Handle bulk operation results
                        if 'uploaded' in response.data:
                            stats = response.data
                            print_header("Bulk Operation Results")
                            print(f"Uploaded: {stats['uploaded']}")
                            print(f"Skipped: {stats['skipped']}")
                            print(f"Errors: {stats['errors']}")

                            if args.format != 'json' and 'files' in stats:
                                print_header("File Details")
                                for file_info in stats['files'][:10]:  # Show first 10
                                    status_color = Colors.OKGREEN if file_info['status'] == 'uploaded' else Colors.WARNING
                                    print(f"  {colored_output(file_info['status'].upper(), status_color)}: {file_info['file']}")

                    elif args.command == 'stats' and args.stats_action == 'overview':
                        # Display comprehensive stats overview
                        stats = response.data
                        overview = stats['system_overview']

                        print_header("System Overview")
                        print(f"Active Documents: {overview['documents']['active']}")
                        print(f"Total Storage: {overview['storage']['total_size_mb']} MB")
                        print(f"Total Chunks: {overview['chunks']['total']}")

                        if 'health_indicators' in stats:
                            print_header("Health Indicators")
                            for indicator, status in stats['health_indicators'].items():
                                color = Colors.OKGREEN if status == 'HEALTHY' else Colors.WARNING
                                print(f"  {indicator.replace('_', ' ').title()}: {colored_output(status, color)}")

                    elif args.command == 'index' and args.index_action == 'status':
                        # Display index status
                        index_data = response.data
                        overview = index_data['overview']

                        print_header("Index Status")
                        print(f"Total Documents: {overview['total_documents']}")
                        print(f"Indexed: {overview['indexed']}")
                        print(f"Processing: {overview['processing']}")
                        print(f"Failed: {overview['failed']}")
                        print(f"Pending: {overview['pending']}")
                        print(f"FTS Entries: {overview['fts_entries']}")

                        if index_data['problem_documents']:
                            print_header("Problem Documents")
                            for doc in index_data['problem_documents'][:5]:
                                status_color = Colors.FAIL if doc['chunking_status'] == 'failed' else Colors.WARNING
                                print(f"  ID {doc['id']}: {doc['title'][:40]}... ({colored_output(doc['chunking_status'], status_color)})")

                    elif args.command == 'maintenance' and args.maintenance_action == 'health-check':
                        # Display health check results
                        health = response.data

                        print_header(f"System Health Check - {health['overall_status']['health_score']}%")
                        print(f"Checks Passed: {health['overall_status']['checks_passed']}/{health['overall_status']['checks_total']}")

                        # Show individual check results
                        checks = [
                            ('Database Connectivity', health['database_connectivity']),
                            ('Table Integrity', health['table_integrity']),
                            ('Index Health', health['index_health']),
                            ('Storage Access', health['storage_access']),
                            ('Service Dependencies', health['service_dependencies'])
                        ]

                        for check_name, passed in checks:
                            status = "✅ PASS" if passed else "❌ FAIL"
                            color = Colors.OKGREEN if passed else Colors.FAIL
                            print(f"  {check_name}: {colored_output(status, color)}")

                        if health['issues_found']:
                            print_header("Issues Found")
                            for issue in health['issues_found']:
                                print_error(f"  - {issue}")

                        if health['recommendations']:
                            print_header("Recommendations")
                            for rec in health['recommendations']:
                                print_info(f"  - {rec}")

            else:
                print_error(response.message)
                for error in response.errors:
                    print_error(f"  - {error}")
                sys.exit(1)

    except KeyboardInterrupt:
        print_warning("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print_error(f"Unexpected error: {str(e)}")
        sys.exit(1)

if __name__ == '__main__':
    main()