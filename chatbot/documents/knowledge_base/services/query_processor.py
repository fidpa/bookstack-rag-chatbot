"""
Query Processor für Knowledge Base
This file now imports from the query_processor package to maintain backwards compatibility
"""

# Import everything from the query_processor package
from .query_processor import QueryProcessor, QueryIntent, QueryAnalysis

# This ensures that imports like:
# from documents.knowledge_base.services.query_processor import QueryProcessor
# continue to work