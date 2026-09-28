"""End to end retrieval: wiki pages and uploads into the prompt context."""

import io

import pytest
from werkzeug.datastructures import FileStorage

from documents.knowledge_base.schema import ensure_kb_schema
from documents.knowledge_base.services import ContextService, IndexingService
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
