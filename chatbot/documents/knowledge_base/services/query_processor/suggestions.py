"""
Query Suggestions
Generates alternative query suggestions
"""

import logging
from typing import List
from .models import QueryIntent

logger = logging.getLogger(__name__)

class QuerySuggestions:
    """Handles query suggestion generation"""
    
    @classmethod
    def suggest_alternative_queries(cls, original_query: str, analysis, found_count: int = 0) -> List[str]:
        """
        Generiert alternative Suchvorschläge wenn keine oder wenige Ergebnisse gefunden wurden
        
        Args:
            original_query: Die ursprüngliche Suchanfrage
            analysis: QueryAnalysis object
            found_count: Anzahl gefundener Ergebnisse
            
        Returns:
            Liste von alternativen Suchvorschlägen
        """
        suggestions = []
        
        # 1. Vereinfachte Version (nur Keywords)
        if analysis.keywords and len(analysis.keywords) > 1:
            simplified = ' '.join(analysis.keywords[:3])
            if simplified != original_query.lower():
                suggestions.append(simplified)
        
        # 2. Einzelne Keywords (bei Multi-Word-Queries)
        if len(analysis.keywords) > 2:
            for keyword in analysis.keywords[:3]:
                if len(keyword) > 4:  # Nur längere Keywords
                    suggestions.append(keyword)
        
        # 3. Ähnliche Begriffe / Synonyme
        synonyms = {
            'reflexivität': ['reflexion', 'reflektieren', 'nachdenken'],
            'team': ['gruppe', 'mannschaft', 'arbeitsgruppe'],
            'methode': ['verfahren', 'ansatz', 'vorgehen'],
            'analyse': ['untersuchung', 'auswertung', 'bewertung'],
            'ergebnis': ['resultat', 'outcome', 'befund'],
            'forschung': ['studie', 'untersuchung', 'wissenschaft']
        }
        
        for keyword in analysis.keywords:
            if keyword in synonyms:
                suggestions.extend(synonyms[keyword][:2])
        
        # 4. Rechtschreibkorrektur (einfache Levenshtein-basierte Vorschläge)
        # Hier könnten wir eine echte Rechtschreibprüfung einbauen
        common_typos = {
            'reflektion': 'reflexion',
            'reflektivität': 'reflexivität',
            'methodik': 'methode',
            'analise': 'analyse'
        }
        
        query_lower = original_query.lower()
        for typo, correct in common_typos.items():
            if typo in query_lower:
                suggestion = query_lower.replace(typo, correct)
                suggestions.append(suggestion)
        
        # 5. Verwandte Fragen (bei Intent-basierten Queries)
        if analysis.intent == QueryIntent.DEFINITION:
            base_term = analysis.entities[0] if analysis.entities else analysis.keywords[0] if analysis.keywords else None
            if base_term:
                suggestions.extend([
                    f"definition {base_term}",
                    f"{base_term} bedeutung",
                    f"{base_term} erklärung"
                ])
        
        # Deduplizierung und Filterung
        seen = set()
        unique_suggestions = []
        for suggestion in suggestions:
            suggestion = suggestion.strip().lower()
            if suggestion and suggestion != original_query.lower() and suggestion not in seen:
                seen.add(suggestion)
                unique_suggestions.append(suggestion)
        
        return unique_suggestions[:5]  # Maximal 5 Vorschläge