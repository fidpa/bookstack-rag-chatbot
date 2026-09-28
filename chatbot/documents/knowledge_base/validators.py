"""
Validation helpers for knowledge-base uploads
"""

import os
import re

# Upload types, limited to what IndexingService can extract text from
ALLOWED_EXTENSIONS = (".pdf", ".docx", ".txt", ".md", ".markdown")


def sanitize_filename(filename: str) -> str:
    """Reduce a filename to [A-Za-z0-9._-], without '..', name part max 100 chars."""
    sanitized = re.sub(r"[^a-zA-Z0-9._-]", "_", filename)
    sanitized = sanitized.replace("..", "_")

    name, ext = os.path.splitext(sanitized)
    return f"{name[:100]}{ext}"
