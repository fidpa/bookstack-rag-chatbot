"""Query analysis: results stay the same, and the cost stays linear."""

import time

import pytest

from documents.knowledge_base.services.query_processor import QueryProcessor
from documents.knowledge_base.services.query_processor.analyzer import QueryAnalyzer


def test_keywords_are_distinct_and_in_question_order():
    assert QueryAnalyzer.extract_keywords(
        "Error 404 error on the self-service portal"
    ) == [
        "error",
        "404",
        "self-service",
        "portal",
        "self",
        "service",
    ]


def test_hyphenated_compounds_contribute_their_parts():
    keywords = QueryAnalyzer.extract_keywords("Self-Service-Portal")
    assert keywords == ["self-service-portal", "self", "service", "portal"]


@pytest.mark.parametrize("capitalised", [False, True])
def test_a_huge_question_is_analysed_in_linear_time(capitalised):
    # Regression: the duplicate check ran against a list, so 40,000 distinct words
    # took 7.6 s and the cost quadrupled with every doubling of the question.
    word = "Begriff" if capitalised else "begriff"
    question = " ".join(f"{word}{i}x" for i in range(60_000))
    started = time.perf_counter()
    analysis = QueryProcessor.analyze_query(question)
    assert time.perf_counter() - started < 3.0
    assert len(analysis.keywords) == 60_000
