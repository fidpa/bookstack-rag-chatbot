"""
Query Preprocessor
Handles query preprocessing for FTS5 (Medical-Aware seit 2025-10-20)
"""

import logging

logger = logging.getLogger(__name__)


class QueryPreprocessor:
    """Handles query preprocessing for search engines"""

    @classmethod
    def preprocess_for_fts5(cls, query: str, enable_medical_boost: bool = True) -> str:
        """
        Bereitet Query für FTS5 vor (mit OR-Semantik + Medical Boost)

        WICHTIG: SQLite FTS5 ist SEHR sensibel bei Sonderzeichen!
        Wir behalten NUR Buchstaben, Zahlen und Leerzeichen.
        WICHTIG: FTS5 verwendet AND-Semantik standardmäßig, aber wir brauchen OR!

        ICD-aware preprocessing added 2025-10-20:
        - Extracts ICD-10 codes (e.g. M05.3, S42.0-) before tokenisation
        - Prepends ICD codes for highest-priority ranking
        - Appends synonyms from MedicalSynonymExpander.MEDICAL_SYNONYMS (empty by default)

        Args:
            query: Raw user query
            enable_medical_boost: Enable ICD-code and synonym boost (default: True)

        Returns:
            FTS5-compatible OR-linked query string

        Examples:
            "What changed in January 2026" → "What OR changed OR January OR 2026"
            "M05.3 Arthritis"             → "M053 OR M05 OR Arthritis"
        """
        import re

        # Phase 1: Medical Term Extraction (VOR Preprocessing!)
        icd_codes = []
        medical_synonyms = []

        if enable_medical_boost:
            try:
                from .medical_extractors import ICDCodeExtractor, MedicalSynonymExpander

                # Extrahiere ICD-Codes
                icd_codes = ICDCodeExtractor.extract_icd_codes(query)

                # Extrahiere medizinische Synonyme
                medical_synonyms = MedicalSynonymExpander.expand_query_with_synonyms(
                    query
                )

                logger.info(
                    f"Medical Boost: ICD={icd_codes}, Synonyms={medical_synonyms[:3]}"
                )

            except ImportError:
                logger.warning(
                    "medical_extractors not available, skipping medical boost"
                )

        # Phase 2: Standard FTS5 Preprocessing
        # ROBUSTER ANSATZ: Behalte nur alphanumerische Zeichen + Leerzeichen
        # Alle Sonderzeichen werden zu Leerzeichen (. ? ! , : ; etc.)
        # Unicode-Safe für deutsche Umlaute (äöüÄÖÜß)
        escaped_query = re.sub(r"[^\w\s]", " ", query, flags=re.UNICODE)

        # Mehrfache Leerzeichen durch einzelnes ersetzen
        escaped_query = re.sub(r"\s+", " ", escaped_query).strip()

        # Fallback für leeren String
        if not escaped_query:
            return "dokument"  # Suche nach irgendetwas

        # OR-Semantik: Verbinde Wörter mit OR
        # Filtere Stopwords und kurze Wörter (< 3 Zeichen)
        stopwords = {
            "und",
            "der",
            "die",
            "das",
            "ist",
            "in",
            "zu",
            "den",
            "dem",
            "von",
            "für",
            "auf",
            "mit",
            "als",
            "bei",
            "es",
            "an",
            "um",
            "am",
            "im",
            "the",
            "a",
            "an",
            "and",
            "or",
            "but",
            "in",
            "on",
            "at",
            "to",
            "for",
        }

        words = [
            w
            for w in escaped_query.split()
            if len(w) >= 3 and w.lower() not in stopwords
        ]

        # Limitiere auf max. 15 Keywords (Performance)
        keywords = words[:15]

        # Verbinde mit OR
        or_query = " OR ".join(keywords)
        base_query = or_query if or_query else escaped_query

        # Phase 3: Medical Boost (ICD-Codes + Synonyme ZUERST)
        if enable_medical_boost and (icd_codes or medical_synonyms):
            boosted_terms = []

            # ICD-Codes (höchste Priorität)
            # WICHTIG: FTS5 tokenisiert "M31.3" als "M31" + "3" (zwei Tokens!)
            # Daher suchen wir nach der BASIS (M31), NICHT "M313"!
            for code in icd_codes:
                if "." in code:
                    # M05.3 → Nutze BASIS "M05" (findet "M05.3", "M05.0", etc.)
                    base_code = code.split(".")[0].replace("-", "")
                    boosted_terms.append(base_code)

                    # Optional: Auch ohne Punkt (für Fälle wo Code ohne Punkt geschrieben wurde)
                    # M05.3 → M053 (niedrigere Priorität)
                    fts5_code_no_dot = code.replace(".", "").replace("-", "")
                    # Nur hinzufügen wenn anders als base_code
                    if fts5_code_no_dot != base_code:
                        boosted_terms.append(fts5_code_no_dot)

                else:
                    # Bereits Basis-Code (M08, S42, etc.)
                    fts5_code = code.replace("-", "")
                    boosted_terms.append(fts5_code)

                    # Erweitere ICD-Familie wenn nötig
                    try:
                        from .medical_extractors import ICDCodeExtractor

                        family_codes = ICDCodeExtractor.expand_icd_family(code)
                        # Top 3 Family-Members (nur Basis-Teil)
                        for fc in family_codes[:3]:
                            base_fc = fc.split(".")[0].replace("-", "")
                            boosted_terms.append(base_fc)
                    except Exception as e:
                        logger.debug(f"ICD-Family-Expansion failed: {e}")

            # Medizinische Synonyme (mittlere Priorität, max 3)
            for syn in medical_synonyms[:3]:
                # Preprocess Synonym ebenfalls
                syn_clean = re.sub(r"[^\w\s]", " ", syn, flags=re.UNICODE)
                syn_clean = re.sub(r"\s+", " ", syn_clean).strip()
                if syn_clean:
                    boosted_terms.append(syn_clean)

            # Deduplizierung
            boosted_terms = list(dict.fromkeys(boosted_terms))

            # Baue finale Query: BOOSTED TERMS FIRST
            final_query = " OR ".join(boosted_terms) + " OR " + base_query

            logger.info(f"Medical-Boosted Query: {len(boosted_terms)} priority terms")

            return final_query

        # Standard-Query (kein Medical Boost)
        return base_query
