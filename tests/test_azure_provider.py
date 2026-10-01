"""The Azure provider against a mocked HTTP transport.

The real `AzureProvider` builds its own `AzureOpenAI` client. Only the transport
underneath it is replaced, so the retry, timeout and error handling under test
are the ones that run in production.
"""

import functools

import pytest

openai = pytest.importorskip("openai")
try:
    import httpx2 as httpx  # openai 3.x ships its own copy of httpx
except ImportError:  # pragma: no cover
    httpx = pytest.importorskip("httpx")

from llm.base import LLMError  # noqa: E402
from llm.providers import azure  # noqa: E402

SECRET = "deployment quota details of the resource SECRET-DETAIL"


@pytest.fixture
def requests_seen():
    return []


@pytest.fixture
def make_provider(monkeypatch, requests_seen):
    """An AzureProvider whose HTTP calls are answered with the given status."""

    def factory(status):
        def handler(request):
            requests_seen.append(request)
            return httpx.Response(
                status,
                json={"error": {"message": SECRET, "code": "x"}},
                headers={"retry-after": "0"},
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "key")
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
        monkeypatch.setattr(
            azure,
            "AzureOpenAI",
            functools.partial(azure.AzureOpenAI, http_client=client),
        )
        # tenacity should not really sleep between attempts
        monkeypatch.setattr(
            azure.AzureProvider._make_api_call.retry, "sleep", lambda s: None
        )
        return azure.AzureProvider()

    return factory


CHAT = [{"role": "user", "content": "hi"}]


def test_the_client_neither_retries_silently_nor_waits_ten_minutes(make_provider):
    # The SDK defaults are two silent retries and a 600 s timeout; with four
    # waitress threads a few hung calls would stall the app.
    provider = make_provider(200)
    assert provider.client.max_retries == 0
    timeout = provider.client.timeout
    assert getattr(timeout, "read", timeout) == azure.REQUEST_TIMEOUT == 60


def test_rate_limits_are_retried_by_tenacity_only(make_provider, requests_seen):
    provider = make_provider(429)
    with pytest.raises(LLMError, match="busy"):
        provider.chat(CHAT)
    assert len(requests_seen) == azure.ATTEMPTS == 3


def test_the_original_exception_reaches_the_handlers(make_provider):
    # reraise=True: without it tenacity raises RetryError and none of the
    # except clauses in chat() would match.
    provider = make_provider(429)
    with pytest.raises(openai.RateLimitError):
        provider._make_api_call(CHAT, 0.7, 10)


@pytest.mark.parametrize(
    "status, message",
    [
        (401, "rejected the configured credentials"),
        (400, "could not process this request"),
        (429, "busy"),
    ],
)
def test_visitors_get_a_short_notice_without_the_provider_error(
    make_provider, status, message
):
    provider = make_provider(status)
    with pytest.raises(LLMError) as raised:
        provider.chat(CHAT)
    assert message in str(raised.value)
    assert "SECRET-DETAIL" not in str(raised.value)


def test_authentication_errors_are_not_retried(make_provider, requests_seen):
    provider = make_provider(401)
    with pytest.raises(LLMError):
        provider.chat(CHAT)
    assert len(requests_seen) == 1
