"""
Advanced Keyword Extraction Service
Intelligente Keyword-Extraktion mit TF-IDF und N-Grammen
"""

import re
import logging
from typing import List, Dict, Tuple
from collections import Counter, defaultdict

logger = logging.getLogger(__name__)


class KeywordExtractor:
    """Service für intelligente Keyword-Extraktion"""
    
    # Erweiterte deutsche Stopwords
    GERMAN_STOPWORDS = {
        # Artikel
        'der', 'die', 'das', 'den', 'dem', 'des', 'ein', 'eine', 'einer', 'eines', 'einen', 'einem',
        # Pronomen
        'ich', 'du', 'er', 'sie', 'es', 'wir', 'ihr', 'mein', 'dein', 'sein', 'unser', 'euer',
        'mir', 'dir', 'ihm', 'uns', 'euch', 'ihnen', 'mich', 'dich', 'sich',
        # Konjunktionen
        'und', 'oder', 'aber', 'doch', 'sondern', 'denn', 'weil', 'dass', 'wenn', 'als', 'wie',
        'sowie', 'sowohl', 'weder', 'noch', 'entweder',
        # Präpositionen
        'für', 'mit', 'bei', 'von', 'zu', 'nach', 'aus', 'auf', 'in', 'im', 'an', 'am',
        'über', 'unter', 'vor', 'hinter', 'zwischen', 'durch', 'gegen', 'ohne', 'um',
        # Hilfsverben
        'ist', 'sind', 'war', 'waren', 'wird', 'werden', 'wurde', 'wurden', 'hat', 'haben',
        'hatte', 'hatten', 'kann', 'können', 'muss', 'müssen', 'soll', 'sollen', 'will', 'wollen',
        'darf', 'dürfen', 'mag', 'mögen', 'möchte', 'möchten',
        # Andere häufige Wörter
        'nicht', 'kein', 'keine', 'auch', 'noch', 'nur', 'schon', 'sehr', 'so', 'dann',
        'also', 'jedoch', 'dabei', 'daher', 'diese', 'dieser', 'dieses', 'jener', 'jene',
        'alle', 'alles', 'man', 'mehr', 'weniger', 'viel', 'viele', 'einige', 'andere'
    }
    
    # Technische Begriffe, die NICHT als Stopwords gelten
    TECHNICAL_EXCEPTIONS = {
        'daten', 'system', 'software', 'hardware', 'computer', 'programm', 'datei',
        'dokument', 'text', 'bild', 'video', 'audio', 'code', 'funktion', 'klasse',
        'methode', 'variable', 'prozess', 'thread', 'speicher', 'netzwerk'
    }
    
    def __init__(self):
        self.document_frequencies = defaultdict(int)
        self.total_documents = 0
    
    def extract_keywords(self, text: str, max_keywords: int = 20, 
                        include_ngrams: bool = True) -> List[Tuple[str, float]]:
        """
        Extrahiert Keywords mit TF-IDF Scoring
        
        Args:
            text: Eingabetext
            max_keywords: Maximale Anzahl Keywords
            include_ngrams: Ob N-Gramme (Phrasen) extrahiert werden sollen
            
        Returns:
            Liste von (keyword, score) Tupeln
        """
        # Text vorbereiten
        tokens = self._tokenize(text)
        
        # Unigrams (einzelne Wörter)
        unigrams = self._extract_unigrams(tokens)
        
        # Bigrams und Trigrams
        ngrams = []
        if include_ngrams:
            bigrams = self._extract_ngrams(tokens, 2)
            trigrams = self._extract_ngrams(tokens, 3)
            ngrams = bigrams + trigrams
        
        # TF-IDF Scoring
        all_terms = unigrams + ngrams
        tf_idf_scores = self._calculate_tf_idf(all_terms, text)
        
        # Nach Score sortieren
        sorted_keywords = sorted(tf_idf_scores.items(), key=lambda x: x[1], reverse=True)
        
        # Top Keywords zurückgeben
        return sorted_keywords[:max_keywords]
    
    def _tokenize(self, text: str) -> List[str]:
        """Tokenisiert Text in Wörter"""
        # Kleinschreibung
        text = text.lower()
        
        # Sonderzeichen entfernen, aber Umlaute behalten
        text = re.sub(r'[^\w\säöüÄÖÜß-]', ' ', text)
        
        # In Wörter aufteilen
        tokens = text.split()
        
        # Kurze Wörter und Zahlen filtern
        tokens = [t for t in tokens if len(t) >= 3 and not t.isdigit()]
        
        return tokens
    
    def _extract_unigrams(self, tokens: List[str]) -> List[str]:
        """Extrahiert einzelne Wörter (Unigrams)"""
        # Stopwords filtern, aber technische Begriffe behalten
        unigrams = []
        for token in tokens:
            if token not in self.GERMAN_STOPWORDS or token in self.TECHNICAL_EXCEPTIONS:
                unigrams.append(token)
        
        return unigrams
    
    def _extract_ngrams(self, tokens: List[str], n: int) -> List[str]:
        """Extrahiert N-Gramme (Wortphrasen)"""
        ngrams = []
        
        for i in range(len(tokens) - n + 1):
            # N aufeinanderfolgende Tokens
            ngram_tokens = tokens[i:i+n]
            
            # Mindestens ein Nicht-Stopword sollte enthalten sein
            non_stopwords = [t for t in ngram_tokens 
                            if t not in self.GERMAN_STOPWORDS or t in self.TECHNICAL_EXCEPTIONS]
            
            if len(non_stopwords) >= n // 2:  # Mindestens die Hälfte sollten keine Stopwords sein
                ngram = ' '.join(ngram_tokens)
                ngrams.append(ngram)
        
        return ngrams
    
    def _calculate_tf_idf(self, terms: List[str], document: str) -> Dict[str, float]:
        """Berechnet TF-IDF Scores für Terme"""
        # Term Frequency (TF)
        term_counts = Counter(terms)
        total_terms = len(terms)
        
        tf_scores = {}
        for term, count in term_counts.items():
            tf_scores[term] = count / total_terms if total_terms > 0 else 0
        
        # Inverse Document Frequency (IDF)
        # Da wir nur ein Dokument haben, verwenden wir eine modifizierte Version
        # basierend auf der Seltenheit des Terms im Dokument
        
        tf_idf_scores = {}
        for term, tf in tf_scores.items():
            # Boost für längere Phrasen
            length_boost = 1 + (0.5 * (len(term.split()) - 1))
            
            # Boost für Großbuchstaben (könnte Akronym sein)
            caps_boost = 1.2 if any(c.isupper() for c in document if term in document.lower()) else 1.0
            
            # Finaler Score
            tf_idf_scores[term] = tf * length_boost * caps_boost
        
        return tf_idf_scores
    
    def update_document_frequencies(self, documents: List[str]):
        """
        Aktualisiert Dokument-Frequenzen für echtes TF-IDF über mehrere Dokumente
        
        Args:
            documents: Liste von Dokumenten für IDF-Berechnung
        """
        self.total_documents = len(documents)
        self.document_frequencies.clear()
        
        for doc in documents:
            tokens = set(self._tokenize(doc))
            for token in tokens:
                self.document_frequencies[token] += 1
    
    def extract_entities(self, text: str) -> Dict[str, List[str]]:
        """
        Extrahiert Named Entities (vereinfachte Version ohne NLP-Library)
        
        Returns:
            Dict mit Entity-Typen und gefundenen Entities
        """
        entities = {
            'emails': [],
            'urls': [],
            'numbers': [],
            'dates': [],
            'capitalized': []
        }
        
        # Email-Adressen
        email_pattern = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
        entities['emails'] = email_pattern.findall(text)
        
        # URLs
        url_pattern = re.compile(r'https?://[^\s]+|www\.[^\s]+')
        raw_urls = url_pattern.findall(text)
        # Clean URLs - remove trailing punctuation
        entities['urls'] = []
        for url in raw_urls:
            # Remove trailing punctuation but keep it if it's part of the URL
            cleaned = url.rstrip('.!?,;:\'"')
            entities['urls'].append(cleaned)
        
        # Zahlen mit Einheiten
        number_pattern = re.compile(r'\b\d+(?:\.\d+)?\s*(?:€|Euro|EUR|USD|GB|MB|KB|%|km|m|cm|mm|kg|g|mg)\b')
        entities['numbers'] = number_pattern.findall(text)
        
        # Datumsangaben (vereinfacht)
        date_pattern = re.compile(r'\b\d{1,2}\.\d{1,2}\.\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b')
        entities['dates'] = date_pattern.findall(text)
        
        # Großgeschriebene Wörter (potenzielle Eigennamen)
        sentences = text.split('.')
        for sentence in sentences:
            words = sentence.strip().split()
            # Überspringe das erste Wort (Satzanfang)
            for word in words[1:]:
                if word and word[0].isupper() and len(word) > 2:
                    clean_word = re.sub(r'[^\w\s]', '', word)
                    if clean_word and clean_word not in self.GERMAN_STOPWORDS:
                        entities['capitalized'].append(clean_word)
        
        # Duplikate entfernen
        for key in entities:
            entities[key] = list(set(entities[key]))
        
        return entities