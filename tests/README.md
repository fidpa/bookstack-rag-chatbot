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
| `test_query_preprocessor.py` | FTS5 query building: operator words, quotes, hyphens and empty queries never become FTS5 syntax |
| `test_sync_service.py` | The BookStack index: full walk over `contents`, ids per type, chunk storage, FTS consistency after updates and deletes, prune safety, legacy schema replacement |
| `test_webhooks.py` | `/webhook/bookstack` with BookStack-shaped payloads, cache invalidation, HMAC check |
| `test_widget.py` | `/chat/api/widget`: sessions, prompt assembly, system prompt default, error handling, rate limit, allow-list with and without a trusted proxy, CORS |
| `test_retrieval.py` | End to end retrieval from wiki pages and uploaded samples into the prompt context |
| `test_bookstack_api.py` | Live API check, marked `integration` |

## Live check against BookStack

Skipped unless `BOOKSTACK_TOKEN_ID` is set. With the stack from `docker/` running:

```bash
set -a; . ./.env; set +a
BOOKSTACK_API_URL=http://localhost:6875 pytest -m integration
```
