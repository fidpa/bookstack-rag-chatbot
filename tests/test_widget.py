"""The widget API: sessions, prompt assembly, errors, access control."""

import pytest

from chat import widget_service
from chat.widget_service import DEFAULT_SYSTEM_PROMPT, WidgetSessionManager
from llm.base import LLMError, LLMProvider
from utils.rate_limiter import rate_limiter


class FakeProvider(LLMProvider):
    def __init__(self, fail=False):
        super().__init__("fake")
        self.calls = []
        self.fail = fail

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        if self.fail:
            raise LLMError("The AI service is busy. Please try again in a minute.")
        return f"answer {len(self.calls)}"

    def is_available(self):
        return True


@pytest.fixture
def provider(monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr(widget_service, "get_llm_provider", lambda: fake)
    return fake


@pytest.fixture
def client(db_path, monkeypatch):
    WidgetSessionManager.clear()
    rate_limiter.clear()
    monkeypatch.delenv("CHATBOT_SYSTEM_PROMPT", raising=False)
    from app import create_app

    return create_app().test_client()


def ask(client, message, session=None, **context):
    headers = {"X-Widget-Session": session} if session else {}
    body = {"message": message}
    if context:
        body["bookstack_context"] = context
    return client.post("/chat/api/widget", json=body, headers=headers)


def test_session_id_from_header_carries_history(client, provider):
    # Regression: the widget sent its session only as a header and the server
    # only read the body, so every message started a new conversation.
    first = ask(client, "Where is the Berlin office?").json
    second = ask(client, "And its opening hours?", session=first["session_id"]).json

    assert second["session_id"] == first["session_id"]
    history = provider.calls[1]["messages"]
    assert {"role": "user", "content": "Where is the Berlin office?"} in history
    assert {"role": "assistant", "content": "answer 1"} in history
    assert history[-1] == {"role": "user", "content": "And its opening hours?"}


def test_unknown_session_id_starts_a_new_session(client, provider):
    r = ask(client, "Hello", session="widget-chosen-by-client").json
    assert r["session_id"] != "widget-chosen-by-client"


def test_empty_system_prompt_variable_uses_the_default(client, provider, monkeypatch):
    # Regression: compose passes CHATBOT_SYSTEM_PROMPT="" and os.getenv
    # returned "" instead of the default, so the model got no instructions.
    monkeypatch.setenv("CHATBOT_SYSTEM_PROMPT", "")
    ask(client, "Hi")
    assert provider.calls[0]["system_prompt"] == DEFAULT_SYSTEM_PROMPT

    monkeypatch.setenv("CHATBOT_SYSTEM_PROMPT", "Answer in haiku.")
    ask(client, "Hi")
    assert provider.calls[1]["system_prompt"] == "Answer in haiku."


def test_page_content_is_sent_once(client, provider):
    page = "The canteen opens at eight. " * 50
    ask(client, "When does it open?", title="Canteen", page_content=page)
    messages = provider.calls[0]["messages"]
    assert (
        sum(m["content"].count("The canteen opens at eight.") for m in messages) == 50
    )
    assert messages[-1]["content"] == "When does it open?"


def test_failed_turn_is_not_stored(client, monkeypatch):
    failing = FakeProvider(fail=True)
    monkeypatch.setattr(widget_service, "get_llm_provider", lambda: failing)
    r = ask(client, "Hi").json
    assert r["response"].startswith("The AI service is busy")
    assert WidgetSessionManager.get_messages(r["session_id"]) == []


def test_no_provider_answers_with_a_notice(client, monkeypatch):
    monkeypatch.setattr(widget_service, "get_llm_provider", lambda: None)
    r = ask(client, "Hi")
    assert r.status_code == 200
    assert "no AI service" in r.json["response"]


def test_errors_do_not_leak_details(client, monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(
        widget_service.WidgetSessionManager, "get_or_create_session", explode
    )
    r = ask(client, "Hi")
    assert "secret internal detail" not in r.get_data(as_text=True)


def test_empty_message_is_rejected(client, provider):
    assert ask(client, "   ").status_code == 400


def test_sessions_are_bounded(monkeypatch):
    WidgetSessionManager.clear()
    monkeypatch.setattr(widget_service, "MAX_SESSIONS", 3)
    ids = [WidgetSessionManager.get_or_create_session() for _ in range(5)]
    assert len(WidgetSessionManager._sessions) == 3
    assert ids[0] not in WidgetSessionManager._sessions


def test_rate_limit(client, provider, monkeypatch):
    for _ in range(30):
        assert ask(client, "Hi").status_code == 200
    assert ask(client, "Hi").status_code == 429


@pytest.mark.parametrize(
    "hops, forwarded, allowed",
    [
        # Default: X-Forwarded-For is ignored, so a forged header cannot pass
        (0, "198.51.100.7", False),
        # Behind one proxy: the rightmost entry (the proxy's view) counts
        (1, "198.51.100.7", True),
        (1, "198.51.100.7, 203.0.113.9", False),
    ],
)
def test_allow_list_uses_the_trusted_address(
    db_path, provider, monkeypatch, hops, forwarded, allowed
):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", str(hops))
    monkeypatch.setenv("ALLOWED_VPN_IPS", "198.51.100.0/24")
    rate_limiter.clear()
    from app import create_app

    client = create_app().test_client()
    r = client.post(
        "/chat/api/widget",
        json={"message": "Hi"},
        headers={"X-Forwarded-For": forwarded},
        environ_base={"REMOTE_ADDR": "192.0.2.10"},
    )
    assert (r.status_code == 200) is allowed


def test_cors_allows_only_known_origins(client, provider):
    ok = client.options(
        "/chat/api/widget",
        headers={
            "Origin": "https://wiki.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert ok.headers.get("Access-Control-Allow-Origin") == "https://wiki.example.com"
    bad = client.options(
        "/chat/api/widget",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "Access-Control-Allow-Origin" not in bad.headers
