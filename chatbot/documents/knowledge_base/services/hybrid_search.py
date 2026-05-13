"""
Hybrid Search Service für Knowledge Base
This file now imports from the hybrid_search package to maintain backwards compatibility
"""

# Import everything from the hybrid_search package
from .hybrid_search import HybridSearchService, SearchStrategy, SearchResult

# This ensures that imports like:
# from documents.knowledge_base.services.hybrid_search import HybridSearchService
# continue to work