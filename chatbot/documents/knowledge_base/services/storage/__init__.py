"""
Storage Service Package für Knowledge Base
Re-exports the main StorageService class to maintain backwards compatibility
"""

from .core import StorageService

__all__ = ["StorageService"]
