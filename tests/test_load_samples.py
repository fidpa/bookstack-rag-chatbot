"""samples/load-samples.py: which token it writes with, and what a refusal says."""

import importlib.util

import pytest

from conftest import ROOT


@pytest.fixture
def loader(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "load_samples", ROOT / "samples" / "load-samples.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("BOOKSTACK_EXTERNAL_URL", "http://wiki.example.com")
    monkeypatch.setenv("BOOKSTACK_TOKEN_ID", "chatbot-id")
    monkeypatch.setenv("BOOKSTACK_TOKEN_SECRET", "chatbot-secret")
    for name in ("SAMPLES_TOKEN_ID", "SAMPLES_TOKEN_SECRET"):
        monkeypatch.delenv(name, raising=False)
    return module


def test_the_samples_token_wins_over_the_chatbot_token(loader, monkeypatch):
    # The chatbot's token is meant to be read-only and cannot create the book.
    monkeypatch.setenv("SAMPLES_TOKEN_ID", "admin-id")
    monkeypatch.setenv("SAMPLES_TOKEN_SECRET", "admin-secret")
    session, _ = loader.make_session()
    assert session.headers["Authorization"] == "Token admin-id:admin-secret"


def test_without_a_samples_token_the_chatbot_token_is_used(loader):
    session, _ = loader.make_session()
    assert session.headers["Authorization"] == "Token chatbot-id:chatbot-secret"


def test_a_refused_book_points_to_the_samples_token(loader):
    class Refused:
        status_code = 403

        def raise_for_status(self):
            raise AssertionError("the 403 must be explained, not raised")

    class Session:
        def post(self, *args, **kwargs):
            return Refused()

    with pytest.raises(SystemExit) as exit_info:
        loader.create_book(Session(), "http://wiki.example.com")
    assert "SAMPLES_TOKEN_ID" in str(exit_info.value)
