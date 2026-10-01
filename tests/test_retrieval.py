"""End to end retrieval: wiki pages and uploads into the prompt context."""

import io

import pytest
from werkzeug.datastructures import FileStorage

from documents.knowledge_base.schema import ensure_kb_schema
from documents.knowledge_base.services import ContextService, IndexingService
from documents.knowledge_base.services.hybrid_search.base_search import (
    SearchImplementations,
)
from documents.knowledge_base.services.hybrid_search.fusion import ResultFusion
from documents.knowledge_base.services.hybrid_search.models import SearchResult
from documents.knowledge_base.services.hybrid_search.strategies import SearchStrategy
from documents.knowledge_base.services.search import SearchService
from documents.knowledge_base.services.storage import StorageService
from conftest import ROOT, fts_integrity


@pytest.fixture
def wiki(sync):
    sync.sync_all()
    return sync


@pytest.fixture
def upload(db_path):
    """The vacation policy sample, uploaded and indexed."""
    sample = ROOT / "samples" / "acme-vacation-policy.md"
    ok, message, doc = StorageService.save_file(
        FileStorage(io.BytesIO(sample.read_bytes()), filename=sample.name),
        title="Vacation policy",
    )
    assert ok, message
    assert IndexingService.index_document(doc.id)[0]
    return doc


def test_wiki_chunk_text_reaches_the_context(wiki):
    # Regression: the model saw a ~50-token snippet per wiki hit, not the chunk.
    context = ContextService.build_knowledge_context("How do I install the agent?")
    assert "Setup" in context
    assert "Port 8080" in context  # from the chunk, beyond the snippet's reach


def set_pages(fake_bookstack, bodies):
    """Replace the fake wiki with top-level pages 1..n holding the given HTML."""
    fake_bookstack.pages = {
        i: {
            "id": i,
            "name": f"Page {i}",
            "book_id": 1,
            "chapter_id": 0,
            "html": f"<p>{html}</p>",
        }
        for i, html in enumerate(bodies, start=1)
    }
    fake_bookstack.chapters = {}
    fake_bookstack.books[1]["contents"] = [
        {"type": "page", "id": i, "url": f"https://wiki.example.com/p/{i}"}
        for i in fake_bookstack.pages
    ]


def test_late_text_of_a_long_page_reaches_the_context(sync, fake_bookstack):
    # Regression: the model saw the FTS5 snippet of a hit (about 64 tokens), so
    # anything further into a page was lost. The pages of the other tests are
    # shorter than the snippet and cannot tell the two apart.
    filler = " ".join(
        f"Sentence {i} explains routine cluster maintenance background."
        for i in range(60)
    )
    set_pages(
        fake_bookstack,
        [
            "Kubernetes upgrade procedure. "
            + filler
            + " The rollback window is exactly 45 minutes after cordoning."
        ],
    )
    sync.sync_all()
    context = ContextService.build_knowledge_context(
        "kubernetes upgrade rollback window"
    )
    assert "45 minutes" in context


def test_stronger_matches_rank_first(sync, fake_bookstack):
    # Regression: the rank was turned into a score with abs() and 1 / (1 + rank),
    # which put the weakest match first.
    set_pages(
        fake_bookstack,
        [
            "Kubernetes upgrade steps. " * 30 + "Kubernetes upgrade checklist.",
            "Notes about backups. One remark on kubernetes upgrade.",
            "Cluster maintenance. " * 20 + "kubernetes",
        ],
    )
    sync.sync_all()
    documents, _ = SearchService.search_documents("kubernetes upgrade", per_page=5)
    assert [d.title for d in documents] == ["Page 1", "Page 2", "Page 3"]
    scores = [d.relevance_score for d in documents]
    assert scores == sorted(scores, reverse=True)


def hit(strategy, score, doc_id="bookstack_1_page"):
    return SearchResult(
        doc_id=doc_id,
        doc_title="Page",
        doc_filename="Page",
        relevance_score=score,
        match_type=strategy,
    )


def test_fusion_counts_each_strategy_once_per_document():
    # The BookStack searches add a second hit to the KEYWORD_OR bucket; that says
    # nothing about agreement between methods.
    ranked = ResultFusion.fuse_and_rank_results(
        {
            SearchStrategy.KEYWORD_OR: [
                hit(SearchStrategy.KEYWORD_OR, 1.0),
                hit(SearchStrategy.KEYWORD_OR, 1.0),
            ],
            SearchStrategy.CHUNK_BASED: [hit(SearchStrategy.CHUNK_BASED, 1.0)],
        }
    )
    assert len(ranked) == 1
    # three hits, two distinct strategies: (1 + 1 + 1) * (1 + 0.5 * 2)
    assert ranked[0].relevance_score == pytest.approx(6.0)


def test_fusion_keeps_the_strategies_apart_between_documents():
    ranked = ResultFusion.fuse_and_rank_results(
        {
            SearchStrategy.KEYWORD_OR: [
                hit(SearchStrategy.KEYWORD_OR, 1.0, "a"),
                hit(SearchStrategy.KEYWORD_OR, 1.0, "b"),
            ],
            SearchStrategy.CHUNK_BASED: [hit(SearchStrategy.CHUNK_BASED, 1.0, "b")],
        }
    )
    assert [r.doc_id for r in ranked] == ["b", "a"]


def test_keyword_hits_in_uploads_carry_a_snippet(upload):
    results = SearchImplementations.search_keywords_or(["vacation"], True)
    assert results and all(r.snippet for r in results)


def test_one_page_takes_one_slot(wiki):
    # Page-level and chunk hits of the same page share an id and merge.
    context = ContextService.build_knowledge_context("annual leave thirty days")
    assert context.count("### Document") == len(
        set(line for line in context.splitlines() if line.startswith("### Document"))
    )
    assert context.count(": Leave") == 1


def test_uploaded_document_is_searchable(upload):
    context = ContextService.build_knowledge_context("How many vacation days per year?")
    assert "Vacation policy" in context
    assert "30 days" in context


def test_operator_words_do_not_break_search(wiki):
    # Regression: an upper-case NOT reached FTS5 as an operator; the syntax
    # error was logged and every BookStack search returned nothing.
    assert "Setup" in ContextService.build_knowledge_context(
        "Why is apt NOT installing?"
    )


def test_nothing_found_gives_empty_context(wiki):
    assert ContextService.build_knowledge_context("zzzqqq") == ""
    assert ContextService.build_knowledge_context("?!") == ""


def test_deleting_an_upload_removes_its_chunks(upload, db):
    from documents.knowledge_base.services.storage.file_operations import delete_file

    assert delete_file(upload.id)[0]
    assert db.execute("SELECT COUNT(*) FROM kb_chunks").fetchone()[0] == 0
    fts_integrity(db, "kb_chunks_fts")


def test_legacy_kb_triggers_are_repaired(db_path, db):
    db.executescript("""
        DROP TRIGGER kb_chunks_ad;
        CREATE TRIGGER kb_chunks_ad AFTER DELETE ON kb_chunks BEGIN
            DELETE FROM kb_chunks_fts WHERE rowid = old.id;
        END;
    """)
    assert ensure_kb_schema(db_path) is True
    assert ensure_kb_schema(db_path) is False
