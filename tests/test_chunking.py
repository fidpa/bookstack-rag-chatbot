"""Chunking of wiki pages and uploads (utils/text_chunking.py and its wrappers)."""

from bookstack.chunking import BookStackChunkingService
from bookstack.sync_service import clean_html_content
from documents.knowledge_base.services.chunking import ChunkingService
from utils.text_chunking import TextChunker


def test_list_without_punctuation_is_split_into_bounded_chunks():
    # Regression: whitespace was collapsed before splitting, so a page made of
    # list items (no sentence marks) became one chunk of any size.
    text = "\n".join(f"- item {i} without punctuation here" for i in range(1200))
    spans = TextChunker(800, 150, 80).split(text)
    assert len(spans) > 1
    assert max(s.word_count for s in spans) <= 800


def test_single_overlong_line_is_windowed():
    spans = TextChunker(800, 150, 80).split(" ".join(["word"] * 5000))
    assert len(spans) > 1
    assert max(s.word_count for s in spans) <= 800


def test_short_sentences_are_kept():
    # Regression: sentences of ten characters or less were dropped.
    spans = TextChunker(800, 150, 80).split("Port 8080. Use sudo. Short.")
    assert spans[0].text == "Port 8080. Use sudo. Short."


def test_consecutive_chunks_overlap():
    sentences = [f"Sentence number {i} talks about topic {i}." for i in range(600)]
    spans = TextChunker(800, 150, 80).split(" ".join(sentences))
    assert len(spans) >= 2
    tail = spans[0].text.split()[-20:]
    assert " ".join(tail) in spans[1].text


def test_near_empty_text_yields_nothing():
    assert TextChunker(800, 150, 80).split("   \n ") == []


def test_bookstack_chunks_are_valid_and_indexed_from_zero():
    service = BookStackChunkingService()
    text = "\n".join(f"Paragraph {i}. It has two sentences." for i in range(800))
    chunks = service.chunk_bookstack_content(text, 7, "page", title="T")
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert service.validate_chunks(chunks) == (True, [])


def test_upload_chunker_uses_its_own_window():
    service = ChunkingService()
    assert (service.chunk_size, service.overlap) == (1000, 200)
    chunks = service.chunk_document("One sentence here. " * 3000, doc_id=3)
    assert all(c.word_count <= 1000 for c in chunks)
    assert chunks[0].to_dict()["doc_id"] == 3


def test_html_cleaning_keeps_block_structure():
    html = (
        "<h2>Setup</h2><p>Install with <b>apt</b>.</p>"
        "<ul><li>Port 8080</li><li>Use sudo</li></ul><script>alert(1)</script>"
    )
    assert clean_html_content(html) == "Setup\nInstall with apt.\nPort 8080\nUse sudo"
