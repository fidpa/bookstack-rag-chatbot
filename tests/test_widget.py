"""The widget API: sessions, prompt assembly, errors, access control."""

import ast
import logging

import pytest

from chat import widget_service
from chat.context_builder import ChatContextBuilder
from chat.widget_service import (
    DEFAULT_SYSTEM_PROMPT,
    MAX_MESSAGE_CHARS,
    WidgetSessionManager,
)
from conftest import ROOT
from documents.knowledge_base.services import ContextService
from llm.base import LLMError, LLMProvider
from utils import rate_limiter as rate_limiter_module
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


def test_overlong_question_is_rejected(client, provider):
    # Regression: a question of any size (16 MB at most) went into keyword
    # extraction, which was quadratic, and into the prompt and the log.
    assert ask(client, "a" * MAX_MESSAGE_CHARS).status_code == 200
    r = ask(client, "a" * (MAX_MESSAGE_CHARS + 1))
    assert r.status_code == 400
    assert "too long" in r.json["error"]
    assert len(provider.calls) == 1


def test_client_supplied_labels_are_bounded(client, provider):
    ask(
        client,
        "Hi",
        title="T" * 3_000_000,
        url="https://wiki.example.com/" + "u" * 100_000,
        page_content="y" * 25_000,
    )
    context = provider.calls[0]["messages"][0]["content"]
    assert "T" * ChatContextBuilder.MAX_TITLE_CHARS in context
    assert "T" * (ChatContextBuilder.MAX_TITLE_CHARS + 1) not in context
    assert "u" * (ChatContextBuilder.MAX_URL_CHARS + 1) not in context
    assert len(context) < 24_000


def test_page_text_is_cut_at_the_context_limit(client, provider):
    ask(client, "Hi", title="Long page", page_content="y" * 25_000)
    context = provider.calls[0]["messages"][0]["content"]
    limit = ChatContextBuilder.PAGE_CONTEXT_CHARS
    assert "y" * limit + "..." in context
    assert "y" * (limit + 1) not in context


def test_non_text_context_fields_are_dropped(client, provider):
    r = ask(client, "Hi", title=["not", "text"], page_content=12345, url={"a": 1})
    assert r.status_code == 200
    assert len(provider.calls) == 1


def test_retrieval_searches_the_question_only(monkeypatch):
    # The page text goes into the prompt; mixed into the search it would decide
    # which keywords are extracted.
    searched = []

    def record(cls, user_query, max_docs=None):
        searched.append(user_query)
        return ""

    monkeypatch.setattr(ContextService, "build_knowledge_context", classmethod(record))
    ChatContextBuilder.build_combined_context(
        "When does it open?",
        {"title": "Canteen", "page_content": "The canteen opens at eight. " * 50},
    )
    assert searched == ["When does it open?"]


def test_idle_sessions_expire(monkeypatch):
    WidgetSessionManager.clear()
    now = [5000.0]
    monkeypatch.setattr(widget_service.time, "time", lambda: now[0])
    session = WidgetSessionManager.get_or_create_session()
    now[0] += widget_service.SESSION_TIMEOUT - 1
    assert WidgetSessionManager.get_or_create_session(session) == session
    now[0] += widget_service.SESSION_TIMEOUT + 1
    assert WidgetSessionManager.get_or_create_session(session) != session


def test_rate_limiter_forgets_idle_clients(monkeypatch):
    from flask import Flask

    now = [1000.0]
    monkeypatch.setattr(rate_limiter_module.time, "time", lambda: now[0])
    limiter = rate_limiter_module.RateLimiter()

    @limiter.limit(max_requests=5, window=60)
    def ping():
        return "ok"

    app = Flask(__name__)

    def hit(address):
        with app.test_request_context(environ_base={"REMOTE_ADDR": address}):
            return ping()

    for address in ("198.51.100.1", "198.51.100.2", "198.51.100.3"):
        hit(address)
    assert len(limiter.requests) == 3

    now[0] += 200  # past both the window and the sweep interval
    hit("198.51.100.4")
    assert list(limiter.requests) == ["198.51.100.4:ping"]


@pytest.fixture
def restore_logging():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield root
    root.handlers[:] = handlers
    root.setLevel(level)


def test_log_level_comes_from_the_environment(monkeypatch, restore_logging):
    import config

    monkeypatch.setenv("LOG_LEVEL", "warning")
    config.setup_logging()
    assert restore_logging.level == logging.WARNING

    monkeypatch.setenv("LOG_LEVEL", "nonsense")
    config.setup_logging()
    assert restore_logging.level == logging.INFO


def test_log_times_follow_tz(monkeypatch):
    import config

    monkeypatch.setenv("TZ", "Europe/Berlin")
    record = logging.LogRecord("x", logging.INFO, "f", 1, "msg", None, None)
    record.created = 1790000000  # 2026-09-21 14:13:20 UTC
    assert config.TimezoneFormatter().formatTime(record) == "2026-09-21 16:13:20 CEST"


def test_running_app_py_binds_to_loopback_only():
    # `python app.py` starts Flask's debugger, which executes code for whoever
    # can reach it.
    tree = ast.parse((ROOT / "chatbot" / "app.py").read_text(encoding="utf-8"))
    hosts = [
        keyword.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "run"
        for keyword in node.keywords
        if keyword.arg == "host"
    ]
    assert hosts == ["127.0.0.1"]


def test_health_reports_the_version(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json["status"] == "healthy" and r.json["version"]


def test_health_fails_when_the_database_setup_failed(db_path, monkeypatch):
    # Regression: with a root-owned volume the migration failed, waitress started
    # anyway and /health, and with it the Docker health check, said "healthy".
    import startup_migrations
    from app import create_app

    monkeypatch.setattr(startup_migrations, "run_startup_migrations", lambda: False)
    r = create_app().test_client().get("/health")
    assert r.status_code == 503
    assert r.json["status"] == "unhealthy"


def test_cors_preflight_allows_the_session_header(client, provider):
    # The widget sends X-Widget-Session; without it in Access-Control-Allow-Headers
    # the browser blocks every message before it leaves the page.
    r = client.options(
        "/chat/api/widget",
        headers={
            "Origin": "https://wiki.example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-widget-session",
        },
    )
    assert r.status_code == 204
    allowed = r.headers["Access-Control-Allow-Headers"].lower()
    assert "x-widget-session" in allowed and "content-type" in allowed


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


@pytest.mark.parametrize(
    "path", ["bookstack-integration/widget.html", "chatbot/templates/chat/widget.html"]
)
def test_the_widget_input_stops_at_the_length_limit(path):
    # The input refuses what the API would refuse, instead of sending it and failing.
    html = (ROOT / path).read_text(encoding="utf-8")
    assert f'maxlength="{MAX_MESSAGE_CHARS}"' in html
