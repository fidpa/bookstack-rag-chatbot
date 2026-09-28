"""FTS5 query building: user text must never turn into FTS5 syntax."""

import sqlite3

import pytest

from documents.knowledge_base.services.query_processor.preprocessor import (
    QueryPreprocessor,
    match_near,
    match_phrase,
    match_prefix,
    search_terms,
)

TRICKY = [
    "Why is it NOT working?",
    "NEAR the office",
    "a AND b OR c",
    'He said "hello',
    "wi-fi password",
    "C++ vs C#",
    "What's the (new) policy: 2026*?",
    "^start",
    "Über Überstunden",
]


@pytest.fixture(scope="module")
def fts():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE VIRTUAL TABLE f USING fts5(t)")
    conn.execute(
        "INSERT INTO f VALUES ('why is it not working near the wi fi office "
        "about the new policy for 2026 and overtime Überstunden')"
    )
    return conn


@pytest.mark.parametrize("query", TRICKY)
def test_or_query_is_valid_fts5(fts, query):
    expr = QueryPreprocessor.preprocess_for_fts5(query)
    assert expr
    fts.execute("SELECT count(*) FROM f WHERE f MATCH ?", (expr,)).fetchone()


def test_operators_are_quoted_as_terms():
    # NEAR is no stopword, so it survives as a term and must arrive quoted
    assert QueryPreprocessor.preprocess_for_fts5("NEAR timeout, proxy*") == (
        '"NEAR" OR "timeout" OR "proxy"'
    )


def test_query_without_words_gives_empty_expression():
    # Regression: fell back to searching for the German word "dokument".
    assert QueryPreprocessor.preprocess_for_fts5("# ?!") == ""


def test_short_tokens_survive_when_nothing_else_does():
    assert search_terms("C vs C#") == ["C", "vs"]


def test_phrase_near_and_prefix_are_valid(fts):
    for expr in (
        match_phrase(["team", "reflexivität"]),
        match_near("wi-fi", "office", 10),
        match_prefix(["polic", "overt"]),
    ):
        fts.execute("SELECT count(*) FROM f WHERE f MATCH ?", (expr,)).fetchone()
    hits = fts.execute(
        "SELECT count(*) FROM f WHERE f MATCH ?", (match_prefix(["polic"]),)
    ).fetchone()[0]
    assert hits == 1


def test_diacritics_fold_in_default_tokenizer(fts):
    hits = fts.execute(
        "SELECT count(*) FROM f WHERE f MATCH ?", ('"uberstunden"',)
    ).fetchone()[0]
    assert hits == 1
