"""
Query Preprocessor
Turns free text into FTS5 MATCH expressions that cannot be misread as syntax.

Every term is emitted as a quoted string. Bare words are FTS5 syntax: a
question containing an upper-case NOT, AND, OR or NEAR, or a hyphen, would
otherwise become an operator and fail with "fts5: syntax error", which the
callers log and turn into an empty result.
"""

import logging
import re
from typing import Iterable, List

from .constants import STOPWORDS

logger = logging.getLogger(__name__)

_TOKEN = re.compile(r"\w+", re.UNICODE)

# More terms than this only slow the query down without changing the top hits
MAX_TERMS = 15


def tokenize(text: str) -> List[str]:
    """Word characters only (letters of any script, digits, underscore)."""
    return _TOKEN.findall(text or "")


def quote(term: str) -> str:
    """One FTS5 string. Several words inside it form a phrase."""
    return '"' + " ".join(tokenize(term)) + '"'


def search_terms(text: str) -> List[str]:
    """
    Distinct search terms of a query, stopwords and one- or two-letter words removed.

    If nothing survives the filter (a query like "C vs C#"), the short tokens
    are kept instead, so the query still searches for something.
    """
    tokens = tokenize(text)
    terms = [t for t in tokens if len(t) >= 3 and t.lower() not in STOPWORDS]
    if not terms:
        terms = [t for t in tokens if t.lower() not in STOPWORDS] or tokens
    return list(dict.fromkeys(terms))[:MAX_TERMS]


def match_any(terms: Iterable[str]) -> str:
    """FTS5 expression matching any of the terms ('' if there are none)."""
    quoted = [quote(t) for t in terms if tokenize(t)]
    return " OR ".join(dict.fromkeys(quoted))


def match_all(terms: Iterable[str]) -> str:
    """FTS5 expression matching all of the terms ('' if there are none)."""
    quoted = [quote(t) for t in terms if tokenize(t)]
    return " AND ".join(dict.fromkeys(quoted))


def match_phrase(terms: Iterable[str]) -> str:
    """FTS5 expression matching the terms as one consecutive phrase."""
    words = [w for t in terms for w in tokenize(t)]
    return quote(" ".join(words)) if words else ""


def match_near(first: str, second: str, distance: int) -> str:
    """FTS5 expression matching both terms within `distance` tokens."""
    if not tokenize(first) or not tokenize(second):
        return ""
    return f"NEAR({quote(first)} {quote(second)}, {int(distance)})"


def match_prefix(terms: Iterable[str]) -> str:
    """FTS5 expression matching any term as a word prefix."""
    quoted = [f"{quote(t)}*" for t in terms if tokenize(t)]
    return " OR ".join(quoted)


class QueryPreprocessor:
    """Handles query preprocessing for search engines"""

    @classmethod
    def preprocess_for_fts5(cls, query: str) -> str:
        """
        Build an OR query of the query's search terms.

        Returns:
            FTS5 MATCH expression, or '' if the query holds no searchable word.
            Callers must skip the search on ''; MATCH '' is a syntax error.

        Examples:
            "What changed in January 2026?" -> '"What" OR "changed" OR "January" OR "2026"'
            "Why is it NOT working?"        -> '"Why" OR "NOT" OR "working"'
        """
        return match_any(search_terms(query))
