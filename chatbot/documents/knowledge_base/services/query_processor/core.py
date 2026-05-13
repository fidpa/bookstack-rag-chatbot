"""
Core Query Processor
Main class coordinating query processing functionality
"""

import logging
from typing import List
from .models import QueryIntent, QueryAnalysis
from .analyzer import QueryAnalyzer
from .suggestions import QuerySuggestions
from .preprocessor import QueryPreprocessor
from .constants import SYNONYMS

logger = logging.getLogger(__name__)

class QueryProcessor:
    """Service für intelligente Query-Verarbeitung"""
    
    @classmethod
    def analyze_query(cls, query: str) -> QueryAnalysis:
        """
        Analysiert eine Such-Query umfassend
        
        Args:
            query: Die zu analysierende Suchanfrage
            
        Returns:
            QueryAnalysis mit allen extrahierten Informationen
        """
        # Basis-Cleaning
        cleaned_query = QueryAnalyzer.clean_query(query)
        
        # Intent erkennen
        intent = QueryAnalyzer.detect_intent(query.lower())
        
        # Keywords extrahieren
        keywords = QueryAnalyzer.extract_keywords(cleaned_query)
        
        # Entities erkennen (Großgeschriebene Wörter, Eigennamen)
        entities = QueryAnalyzer.extract_entities(query)
        
        # Must-have und nice-to-have Terms bestimmen
        must_have, nice_to_have = QueryAnalyzer.categorize_terms(keywords, entities, intent)
        
        # Such-Queries generieren
        search_queries = cls._generate_search_queries(
            keywords, entities, intent, query
        )
        
        return QueryAnalysis(
            original_query=query,
            cleaned_query=cleaned_query,
            keywords=keywords,
            entities=entities,
            intent=intent,
            search_queries=search_queries,
            must_have_terms=must_have,
            nice_to_have_terms=nice_to_have
        )
    
    @classmethod
    def _generate_search_queries(cls, keywords: List[str], entities: List[str],
                               intent: QueryIntent, original_query: str) -> List[str]:
        """Generiert verschiedene Such-Varianten"""
        queries = []
        
        # 1. Original Query (bereinigt)
        cleaned = QueryAnalyzer.clean_query(original_query)
        if cleaned:
            queries.append(cleaned)
        
        # 2. Nur Keywords (OR-verknüpft)
        if keywords:
            keyword_query = ' OR '.join(keywords[:5])  # Max 5 Keywords
            queries.append(keyword_query)
        
        # 3. Entities fokussiert
        if entities:
            entity_query = ' '.join(entities)
            queries.append(entity_query)
        
        # 4. Phrase-Suche für wichtigste Begriffe
        if len(keywords) >= 2:
            # Kombiniere die 2 wichtigsten Keywords
            phrase_query = f'"{keywords[0]} {keywords[1]}"'
            queries.append(phrase_query)
        
        # 5. Synonym-erweiterte Queries
        expanded_queries = cls._expand_with_synonyms(keywords)
        queries.extend(expanded_queries[:2])  # Max 2 erweiterte Queries
        
        # 6. Intent-spezifische Queries
        if intent == QueryIntent.DEFINITION and keywords:
            queries.append(f'definition {keywords[0]}')
            queries.append(f'was ist {keywords[0]}')
        elif intent == QueryIntent.EXPLANATION and keywords:
            queries.append(f'{keywords[0]} funktionsweise')
            queries.append(f'{keywords[0]} ablauf')
        
        # Deduplizierung und Begrenzung
        unique_queries = []
        seen = set()
        for q in queries:
            q_lower = q.lower().strip()
            if q_lower and q_lower not in seen:
                unique_queries.append(q)
                seen.add(q_lower)
        
        return unique_queries[:6]  # Maximal 6 Queries
    
    @classmethod
    def _expand_with_synonyms(cls, keywords: List[str]) -> List[str]:
        """Erweitert Keywords mit Synonymen"""
        expanded_queries = []
        
        for keyword in keywords[:3]:  # Nur Top 3 Keywords
            keyword_lower = keyword.lower()
            if keyword_lower in SYNONYMS:
                synonyms = SYNONYMS[keyword_lower]
                # Erstelle Query mit Keyword und Synonymen
                synonym_query = f'{keyword} OR {" OR ".join(synonyms[:2])}'
                expanded_queries.append(synonym_query)
        
        return expanded_queries
    
    @classmethod
    def preprocess_for_fts5(cls, query: str) -> str:
        """Wrapper für FTS5 preprocessing"""
        return QueryPreprocessor.preprocess_for_fts5(query)
    
    @classmethod
    def suggest_alternative_queries(cls, original_query: str, found_count: int = 0) -> List[str]:
        """Wrapper für alternative query suggestions"""
        # Analysiere die ursprüngliche Query
        analysis = cls.analyze_query(original_query)
        return QuerySuggestions.suggest_alternative_queries(original_query, analysis, found_count)
    
    @classmethod
    def get_search_explanation(cls, analysis: QueryAnalysis) -> str:
        """Erstellt eine Erklärung der Suche für Debug/UI"""
        explanation = f"Suche nach: {analysis.original_query}\n"
        explanation += f"Intent: {analysis.intent.value}\n"
        explanation += f"Hauptbegriffe: {', '.join(analysis.must_have_terms)}\n"
        explanation += f"Weitere Begriffe: {', '.join(analysis.nice_to_have_terms)}\n"
        explanation += f"Suchvarianten: {len(analysis.search_queries)}"
        
        return explanation