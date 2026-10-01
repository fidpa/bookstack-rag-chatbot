# Tests

A pytest suite that runs without BookStack, an LLM or Docker, plus two optional live
checks against a real BookStack.

```bash
pip install -r chatbot/requirements.txt
pytest -q
```

`conftest.py` puts `chatbot/` on the import path, points `DATABASE_PATH` at a temporary
directory before any application module is imported, and gives each test a fresh
database with the full schema. `FakeBookStack` stands in for the REST API with one book,
one chapter and two pages; the book, the chapter and one page share id 1, as they do in
real BookStack instances.

| File | Covers |
|---|---|
| `test_chunking.py` | `TextChunker` and both chunking services: bounded chunks, overlap, short sentences, HTML cleaning |
| `test_query_analyzer.py` | Keyword extraction: same result, linear time on a huge question |
| `test_query_preprocessor.py` | FTS5 query building: operator words, quotes, hyphens and empty queries never become FTS5 syntax |
| `test_sync_service.py` | The BookStack index: full walk over `contents`, ids per type, chunk storage, FTS consistency after updates and deletes, prune safety (including a failed book listing), legacy schema replacement |
| `test_api_client.py` | The real `BookStackClient` over a stand-in wire: paging, error handling, timeouts, no stale reads after a move |
| `test_resync.py` | `resync.py`: report and exit code, also when BookStack is unreachable |
| `test_webhooks.py` | `/webhook/bookstack` with BookStack-shaped payloads, payload URL, HMAC check, the queued sync with its retries |
| `test_webhook_worker.py` | The background worker behind the webhooks: order, delays, retries, giving up, the queue limit |
| `test_widget.py` | `/chat/api/widget`: sessions, prompt assembly, size limits, system prompt default, error handling, rate limit, allow-list with and without a trusted proxy, CORS, `/health`, logging |
| `test_widget_js.py` | Both widget scripts run in node (`tests/js/widget_harness.js`): API URL with port, session id, `postMessage` origin; skipped without node |
| `test_azure_provider.py` | `AzureProvider` against a mocked transport: retries, timeout, `reraise`, no provider error text for visitors |
| `test_retrieval.py` | End to end retrieval from wiki pages and uploaded samples into the prompt context |
| `test_compose.py` | `docker/docker-compose.yml`: chatbot port on loopback by default, every variable it reads is in `.env.example`, the chatbot's user owns its data |
| `test_bookstack_api.py` | Live API check, marked `integration` |

## Live check against BookStack

Skipped unless `BOOKSTACK_TOKEN_ID` is set. With the stack from `docker/` running:

```bash
(set -a; . ./.env; set +a; BOOKSTACK_API_URL=http://localhost:6875 pytest -m integration)
```
