"""
Medical Term Extractors
ICD-10 code extraction and configurable synonym expansion for domain-specific wikis.
"""

import re
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)


class ICDCodeExtractor:
    """Extrahiert ICD-10-Codes aus Queries und Text"""

    # ICD-10 Patterns (M, S, Z, etc. + 2 Ziffern + Punkt + 0-2 Ziffern)
    ICD10_PATTERN = re.compile(r'\b([A-Z]\d{2})\.?(\d{0,2})\-?\b', re.IGNORECASE)

    @classmethod
    def extract_icd_codes(cls, text: str) -> List[str]:
        """
        Extrahiert ICD-10-Codes aus Text

        Args:
            text: Text mit potentiellen ICD-Codes

        Returns:
            Liste von ICD-Codes (normalisiert: "M05.3", "S42.0-", etc.)

        Examples:
            "M05.3" → ["M05.3"]
            "M053" → ["M05.3"]
            "M05-" → ["M05"]
            "juvenile Arthritis M08" → ["M08"]
        """
        codes = []

        for match in cls.ICD10_PATTERN.finditer(text):
            base = match.group(1).upper()  # z.B. "M05"
            subcode = match.group(2)  # z.B. "3" oder ""

            # Normalisiere Format
            if subcode:
                if len(subcode) == 1:
                    # M053 → M05.3
                    code = f"{base}.{subcode}"
                else:
                    # M0503 → M05.03
                    code = f"{base}.{subcode}"
            else:
                # M05 → M05 (Familie)
                code = base

            # Prüfe ob Trailing Dash (M08.0- → M08.0-)
            if text[match.end():match.end()+1] == '-':
                code += '-'

            codes.append(code)

        # Deduplizierung
        return list(dict.fromkeys(codes))

    @classmethod
    def expand_icd_family(cls, icd_code: str) -> List[str]:
        """
        Erweitert ICD-Familie zu konkreten Codes

        Args:
            icd_code: ICD-Code (z.B. "M08")

        Returns:
            Liste von konkreten Codes (["M08.0-", "M08.1-", ...])

        Examples:
            "M08" → ["M08.0-", "M08.1-", "M08.2-", "M08.3", "M08.4-", ...]
            "M05.3" → ["M05.3"] (bereits konkret)
        """
        # Wenn bereits konkret → direkt zurück
        if '.' in icd_code:
            return [icd_code]

        # ICD-Familie → Generiere .0 bis .9 Varianten
        expanded = []
        base = icd_code.upper()

        # Standard-Subcodes 0-9
        for i in range(10):
            expanded.append(f"{base}.{i}-")  # Mit Trailing-Dash
            expanded.append(f"{base}.{i}")   # Ohne Trailing-Dash

        return expanded

    @classmethod
    def get_icd_boost_query(cls, original_query: str, icd_codes: List[str]) -> Tuple[str, float]:
        """
        Erstellt boosted FTS5-Query mit ICD-Codes

        Args:
            original_query: Preprocessed FTS5-Query (OR-Semantik)
            icd_codes: Extrahierte ICD-Codes

        Returns:
            (boosted_query, boost_factor)

        Examples:
            ("M05 OR Arthritis", ["M05.3"])
            → ("M05.3 OR M05 OR Arthritis", 3.0)
        """
        if not icd_codes:
            return (original_query, 1.0)

        # Erweitere ICD-Familien
        expanded_codes = []
        for code in icd_codes:
            if '.' not in code:
                # Familie → Erweitere
                expanded_codes.extend(cls.expand_icd_family(code)[:5])  # Top 5
            else:
                # Konkreter Code
                expanded_codes.append(code)

        # Entferne Punkte für FTS5 (M05.3 → M053 wegen FTS5-Preprocessing)
        fts5_codes = [code.replace('.', '').replace('-', '') for code in expanded_codes]

        # Deduplizierung
        fts5_codes = list(dict.fromkeys(fts5_codes))

        # Boost-Query: ICD-Codes ZUERST (höchste Priorität)
        boosted_query = ' OR '.join(fts5_codes) + ' OR ' + original_query

        # Boost-Factor für Ranking
        boost_factor = 3.0  # ICD-Code-Matches werden 3x höher gerankt

        logger.info(f"ICD-Boost: {icd_codes} → {fts5_codes[:3]}... (boost={boost_factor})")

        return (boosted_query, boost_factor)


class MedicalSynonymExpander:
    """Expands queries with domain-specific synonyms and acronyms.

    Populate MEDICAL_SYNONYMS with terminology relevant to your wiki.
    Keys are lowercase terms; values are lists of equivalent terms/codes.

    Example entry:
        'heart failure': ['cardiac failure', 'CHF', 'I50'],
    """

    # Domain-specific synonym dictionary — empty by default, extend for your wiki.
    MEDICAL_SYNONYMS: dict[str, list[str]] = {}

    @classmethod
    def expand_query_with_synonyms(cls, query: str) -> List[str]:
        """
        Expand a query with synonyms from MEDICAL_SYNONYMS.

        Args:
            query: Original query (lowercase)

        Returns:
            List of synonyms/acronyms found for terms in the query
        """
        query_lower = query.lower()
        synonyms = []

        # Suche nach Matches in Dictionary
        for term, term_synonyms in cls.MEDICAL_SYNONYMS.items():
            if term in query_lower:
                synonyms.extend(term_synonyms)
                logger.debug(f"Synonym-Expansion: '{term}' → {term_synonyms[:2]}...")

        # Deduplizierung
        return list(dict.fromkeys(synonyms))

    @classmethod
    def get_expanded_query(cls, original_query: str, max_synonyms: int = 5) -> str:
        """
        Return original_query extended with OR-linked synonyms from MEDICAL_SYNONYMS.

        Args:
            original_query: Preprocessed FTS5 query string
            max_synonyms: Maximum number of synonyms to append

        Returns:
            OR-linked expanded query string
        """
        synonyms = cls.expand_query_with_synonyms(original_query)

        if not synonyms:
            return original_query

        # Begrenze Synonyme (Performance)
        limited_synonyms = synonyms[:max_synonyms]

        # Append zu Original-Query
        expanded = original_query + ' OR ' + ' OR '.join(limited_synonyms)

        logger.info(f"Synonym-Expansion: +{len(limited_synonyms)} Terme ({limited_synonyms[:3]}...)")

        return expanded


# Export
__all__ = ['ICDCodeExtractor', 'MedicalSynonymExpander']
