"""
Query Analyzer
Core analysis functions for query processing
"""

import re
import logging
from typing import List, Tuple
from .models import QueryIntent
from .constants import GERMAN_STOPWORDS, INTENT_PATTERNS

logger = logging.getLogger(__name__)


class QueryAnalyzer:
    """Handles query analysis and intent detection"""

    @classmethod
    def clean_query(cls, query: str) -> str:
        """Bereinigt die Query von Sonderzeichen"""
        # Satzzeichen am Ende entfernen
        query = re.sub(r"[.!?]+$", "", query)

        # Mehrfache Leerzeichen normalisieren
        query = re.sub(r"\s+", " ", query)

        return query.strip()

    @classmethod
    def detect_intent(cls, query: str) -> QueryIntent:
        """Erkennt den Intent der Query"""
        query_lower = query.lower()

        # Prüfe Intent-Patterns
        for intent, patterns in INTENT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, query_lower):
                    return intent

        # Spezielle Heuristiken
        if "?" in query:
            if query_lower.startswith(("was", "wer", "wo", "wann")):
                return QueryIntent.DEFINITION
            elif query_lower.startswith("wie"):
                return QueryIntent.EXPLANATION

        # Default
        return QueryIntent.GENERAL

    @classmethod
    def extract_keywords(cls, query: str) -> List[str]:
        """Extrahiert wichtige Keywords aus der Query"""
        # Tokenisierung
        words = re.findall(r"\b[a-zA-ZäöüÄÖÜß-]+\b", query.lower())

        # Stopwords filtern
        keywords = []
        for word in words:
            if len(word) >= 3 and word not in GERMAN_STOPWORDS:
                keywords.append(word)

        # Compound-Words erkennen (wichtig für Deutsch)
        # z.B. "Team-Reflexivität" -> ["team", "reflexivität", "team-reflexivität"]
        compound_pattern = re.findall(
            r"\b[a-zA-ZäöüÄÖÜß]+-[a-zA-ZäöüÄÖÜß]+\b", query.lower()
        )
        for compound in compound_pattern:
            if compound not in keywords:
                keywords.append(compound)
            # Teile auch hinzufügen
            parts = compound.split("-")
            for part in parts:
                if (
                    len(part) >= 3
                    and part not in GERMAN_STOPWORDS
                    and part not in keywords
                ):
                    keywords.append(part)

        return keywords

    @classmethod
    def extract_entities(cls, query: str) -> List[str]:
        """Extrahiert Entities (Eigennamen, spezielle Begriffe)"""
        entities = []

        # Großgeschriebene Wörter (außer am Satzanfang)
        words = query.split()
        for i, word in enumerate(words):
            # Bereinige Satzzeichen
            clean_word = re.sub(r"[^\w\säöüÄÖÜß-]", "", word)

            # Prüfe ob Großgeschrieben und kein Satzanfang
            if (
                i > 0
                and clean_word
                and clean_word[0].isupper()
                and clean_word.lower() not in GERMAN_STOPWORDS
            ):
                entities.append(clean_word)

        # Spezielle Patterns (z.B. Abkürzungen)
        # Findet Wörter in Großbuchstaben oder mit Punkten
        special_patterns = re.findall(r"\b[A-Z]{2,}\b|\b[A-Z]\.[A-Z]\.?\b", query)
        entities.extend(special_patterns)

        # Deduplizierung
        return list(set(entities))

    @classmethod
    def categorize_terms(
        cls, keywords: List[str], entities: List[str], intent: QueryIntent
    ) -> Tuple[List[str], List[str]]:
        """Kategorisiert Terms in must-have und nice-to-have"""
        must_have = []
        nice_to_have = []

        # Entities sind meist must-have
        must_have.extend(entities)

        # Bei Definition/Explanation sind Hauptbegriffe must-have
        if intent in [
            QueryIntent.DEFINITION,
            QueryIntent.EXPLANATION,
            QueryIntent.SPECIFIC,
        ]:
            # Die längsten Keywords sind oft die wichtigsten
            sorted_keywords = sorted(keywords, key=len, reverse=True)
            if sorted_keywords:
                must_have.extend(sorted_keywords[:2])  # Top 2 längste Keywords
                nice_to_have.extend(sorted_keywords[2:])
        else:
            # Bei general search sind alle Keywords nice-to-have
            nice_to_have.extend(keywords)

        # Deduplizierung
        must_have = list(set(must_have))
        nice_to_have = [term for term in set(nice_to_have) if term not in must_have]

        return must_have, nice_to_have
