"""The two widget scripts, run in node against DOM stand-ins.

`tests/js/widget_harness.js` loads the real scripts (the embedded `widget.html` and
the standalone chat page) and reports what they did. Skipped when node is missing.
"""

import json
import shutil
import subprocess

import pytest

from conftest import ROOT

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


@pytest.fixture(scope="module")
def js():
    run = subprocess.run(
        [NODE, str(ROOT / "tests" / "js" / "widget_harness.js")],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return json.loads(run.stdout)


def test_the_embedded_widget_posts_to_the_page_origin_including_the_port(js):
    urls = js["apiUrl"]
    # Regression: the URL was built from protocol and hostname, so BookStack on
    # https://wiki.example.com:8443 posted to port 443.
    assert urls["https://wiki.example.com:8443/books/a/page/b"] == (
        "https://wiki.example.com:8443/chat/api/widget"
    )
    assert urls["http://wiki.lan/books/a/page/b"] == "http://wiki.lan/chat/api/widget"


def test_the_embedded_widget_uses_the_published_port_on_localhost(js):
    urls = js["apiUrl"]
    assert urls["http://localhost:6875/books/x/page/y"] == (
        "http://localhost:8888/chat/api/widget"
    )
    assert urls["http://127.0.0.1:6875/"] == "http://127.0.0.1:8888/chat/api/widget"


def test_the_embedded_widget_keeps_the_session_id_the_server_issued(js):
    # Regression: the widget ignored the id in the answer, so every message
    # started a new conversation.
    embedded = js["embedded"]
    assert embedded["headers"] == ["", "srv-1"]
    assert embedded["stored"] == [["knowledgebot-widget-session", "srv-1"]]


def test_the_embedded_widget_sends_the_page_context_the_server_reads(js):
    assert {"title", "url", "page_content"} <= set(js["embedded"]["sentContext"])


def test_the_standalone_page_takes_page_context_only_from_bookstack(js):
    # Regression: any page framing /chat/widget could put text into the prompt.
    page = js["standalone"]
    assert page["afterForeignOrigin"] == page["before"]
    assert page["afterWrongPort"] == page["before"]
    assert page["afterBookStack"] == "from BookStack"


def test_the_standalone_page_keeps_the_session_id_the_server_issued(js):
    page = js["standalone"]
    assert page["headers"] == ["", "srv-9"]
    assert page["stored"] == [["knowledgebot-widget-session", "srv-9"]]


def test_both_widgets_show_why_the_api_refused_a_question(js):
    # Regression: a 400 (a question over the length limit) showed as
    # "Connection error: HTTP error! status: 400", and the API's reason was lost.
    for shown in js["refused"].values():
        assert len(shown) == 1
        assert "Message too long" in shown[0]
        assert "Connection error" not in shown[0]
