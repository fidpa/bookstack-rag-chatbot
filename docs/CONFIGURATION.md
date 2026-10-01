# Configuration Reference

Every environment variable the chatbot reads, in the order it appears in `.env.example`.

The Required column says whether the software insists. Several variables that are
**not** required have defaults you should still override; those are called out in the
Purpose column and repeated in the checklist in [SECURITY.md](SECURITY.md).

## Core

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `SECRET_KEY` | No, but set it | `chatbot-dev-secret-change-in-production` | Flask's signing key. The app sets no cookies today, but `chatbot/config.py` falls back to a literal published in this repository, so set a real one before anything starts relying on it. Generate with `openssl rand -hex 32`. |
| `TZ` | No | `UTC` | Timezone of log timestamps and of the sync time stored with each indexed item, and of the containers. IANA names, e.g. `Europe/Berlin`. An unknown name falls back to UTC. |
| `FLASK_DEBUG` | No | `false` | `true` makes `/debug` return the URL map instead of a 403. The container always runs waitress, so this never enables Flask's interactive debugger; only `python app.py` does that, bound to 127.0.0.1. |
| `LOG_LEVEL` | No | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR`, for the app and for `resync.py`. At `INFO` the log carries the keywords of each question; `WARNING` keeps question content out of it. |

## LLM Providers

At least one provider must be configured. `get_llm_provider()` in
`chatbot/llm/factory.py` returns Azure when it is configured, else Ollama when it is
enabled and reachable, else nothing; the widget then answers with a notice that no AI
service is available.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `AZURE_OPENAI_API_KEY` | If using Azure | none | Azure OpenAI API key. The provider is only considered when this **and** `AZURE_OPENAI_ENDPOINT` are set. |
| `AZURE_OPENAI_ENDPOINT` | If using Azure | none | Full endpoint URL, e.g. `https://my-resource.openai.azure.com/`. |
| `AZURE_OPENAI_API_VERSION` | No | `2025-01-01-preview` | API version. |
| `AZURE_OPENAI_DEPLOYMENT_NAME` | If using Azure | `gpt-4o-mini` in compose | Name of the deployment in Azure (not the model name). Without it the code falls back to `gpt-35-turbo`. |
| `OLLAMA_BASE_URL` | If using Ollama | `http://host.docker.internal:11434` | URL of an Ollama instance reachable from the chatbot container. |
| `OLLAMA_MODEL` | No | `mistral:latest` | Ollama model tag. It must be pulled (`ollama pull mistral`), otherwise the provider counts as unavailable. |
| `ENABLE_OLLAMA_FALLBACK` | No | `false` | Set to `true` to allow Ollama when Azure is not configured. Disabled by default, so a missing Azure key does not silently hand answers to a weaker local model. |

## BookStack Integration

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `BOOKSTACK_EXTERNAL_URL` | Yes | `http://localhost:6875` | Public URL of BookStack, as browsers see it. Its origin is the allowed CORS origin of the widget API and the only origin `/chat/widget` accepts page context from; `/` redirects to it; page links in the index are built on it when the API does not return one. |
| `BOOKSTACK_PORT` | No | `6875` | Host port that BookStack is published on. |
| `BOOKSTACK_APP_KEY` | Yes (BookStack) | none | BookStack's APP_KEY. Generate once and pin. See `.env.example` for the command. |
| `BOOKSTACK_TOKEN_ID` | Yes | none | BookStack API token ID. Create in BookStack: Settings → Users → (the token's user) → API Tokens, or My Account → Access & Security → API Tokens for your own account. |
| `BOOKSTACK_TOKEN_SECRET` | Yes | none | BookStack API token secret. Shown only once at creation time. |
| `SAMPLES_TOKEN_ID`, `SAMPLES_TOKEN_SECRET` | No | empty | Read by `samples/load-samples.py` only, never by the container. The loader creates a book and pages, which the chatbot's read-only token may not; with these empty it falls back to `BOOKSTACK_TOKEN_*`. Use an admin's token and delete it after loading. |
| `BOOKSTACK_WEBHOOK_SECRET` | No | empty | Setting it turns on the HMAC-SHA256 check in `chatbot/bookstack/webhooks.py`, which then **requires** an `X-BookStack-Signature` header. BookStack v25.07 does not send one, so against stock BookStack this makes every delivery fail with 401. Leave empty. |

## Database (MariaDB for BookStack)

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `BOOKSTACK_DB_PASSWORD` | Yes | none | Password for the BookStack DB user. |
| `MYSQL_ROOT_PASSWORD` | Yes | none | MariaDB root password. |

## Chatbot

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `CHATBOT_PORT` | No | `8888` | Host port for the chatbot's HTTP API. |
| `CHATBOT_BIND` | No | `127.0.0.1` | Host address that port is published on. Loopback keeps the chatbot unreachable from the network, which is what `TRUSTED_PROXY_HOPS=1` requires behind a proxy; set `0.0.0.0` only if clients must reach it directly (that publishes on IPv4 only). Up to v0.3.0 the port was always published on all interfaces. |
| `CHATBOT_SYSTEM_PROMPT` | No | see below | Replaces the widget's default system prompt wholesale. Empty or unset means the default, `DEFAULT_SYSTEM_PROMPT` in `chatbot/chat/widget_service.py`, which tells the model to use both sources, cite them briefly, say so when the sources do not answer, and reply in the user's language. |
| `DATABASE_PATH` | No | `/app/data/chatbot.db` in the container | SQLite file. Without it, every component falls back to `chatbot/data/chatbot.db` next to the code (`utils/database.get_db_path()`). `resync.py`, `kb_admin.py` and `init_kb_schema.py` read the same variable. Uploaded files are stored in `knowledge_base/` next to it. |
| `BOOKSTACK_API_URL` | No | `http://bookstack:80` | Where the chatbot reaches the BookStack API. Set in `docker-compose.yml` to the Docker-internal hostname. |
| `PORT` | No | `8888` | Port for `python app.py` (local development only; the container ignores it). |

## Access Control

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `ALLOWED_VPN_IPS` | No, but set it | empty | Comma-separated CIDRs allowed to reach `/chat/api/*` and `/webhook/bookstack`. Example: `10.0.0.0/8,192.168.0.0/16`. **Empty means allow all**, logged as a warning on the first guarded request. A non-empty value with no parseable CIDR denies everything instead. Webhooks come from the BookStack container, so include the Docker network (e.g. `172.16.0.0/12`). |
| `IP_ACCESS_CONTROL` | No | `true` | Set to `false` to bypass the allow-list (development only). |
| `RATE_LIMIT_PER_MINUTE` | No | `30` | Sliding-window per-IP limit on `/chat/api/widget`. Read at startup; a non-integer value logs a warning and falls back to 30. |
| `TRUSTED_PROXY_HOPS` | No | `0` | How many reverse proxies to look through for the client address. `0`: `X-Forwarded-For` is ignored and the connecting address counts. `1`: the entry the proxy appended counts (werkzeug `ProxyFix`); entries a client sent are ignored. Set it only if port 8888 is unreachable around the proxy. |

## Hidden / Advanced

These knobs live in Python, not env vars. Edit the listed file to change.

| Setting | Default | Where | Purpose |
|---|---|---|---|
| `BookStackChunkingService.DEFAULTS` | `chunk_size` 800, `overlap` 150, `min_size` 80 (words) | `chatbot/bookstack/chunking.py` | Chunking of wiki pages. `overlap` must be smaller than `chunk_size`. |
| `ChunkingService.DEFAULTS` | `chunk_size` 1000, `overlap` 200, `min_size` 100 (words) | `chatbot/documents/knowledge_base/services/chunking.py` | Chunking of uploaded documents. Both use `chatbot/utils/text_chunking.py`. |
| `ContextService.MAX_CONTEXT_DOCS` | `3` | `chatbot/documents/knowledge_base/services/context.py` | Documents (wiki items or uploads) that contribute excerpts, up to three excerpts each. |
| `ChatContextBuilder.PAGE_CONTEXT_CHARS` | `20000` | `chatbot/chat/context_builder.py` | Characters of the page the visitor is on that go into the prompt. |
| `ChatContextBuilder.MAX_TITLE_CHARS`, `MAX_URL_CHARS` | `300`, `2000` | `chatbot/chat/context_builder.py` | Longest page title and URL taken from the widget's context. |
| `SYNC_DELAY_SECONDS`, `RETRY_DELAYS`, `RESTORE_DELAY_SECONDS` | `2.0`, `(3.0, 6.0, 12.0)`, `5.0` | `chatbot/bookstack/webhooks.py` | When a queued webhook is synced, how often a create event, any event while BookStack does not answer, or a recycle-bin walk that could not list the books is retried, in seconds after the previous attempt, and how long a recycle-bin restore waits. |
| `RATE_LIMIT_WAITS`, `RATE_LIMIT_MAX_WAIT`, `RATE_LIMIT_FALLBACK_WAIT` | `5`, `60`, `10` | `chatbot/bookstack/api_client.py` | How a `429` from BookStack's API rate limit is handled: waits per request before the request fails, the cap on BookStack's `Retry-After` in seconds (one second is added to every wait), and the wait when `Retry-After` is missing or not a number. |
| `WebhookWorker(max_pending=…)` | `500` | `chatbot/bookstack/webhook_worker.py` | Webhook jobs that may wait at once; more are answered with `503`. |
| `MAX_MESSAGE_CHARS` | `2000` | `chatbot/chat/widget_service.py` | Longest question the widget API accepts; longer ones get `400`. |
| `SYNONYMS` | empty | `chatbot/documents/knowledge_base/services/query_processor/constants.py` | Query expansion per keyword, for your wiki's vocabulary. |
| `Config.MAX_CONTENT_LENGTH` | `16 MB` | `chatbot/config.py` | Flask's request-body cap. |
| `ALLOWED_EXTENSIONS` | `.pdf .docx .txt .md .markdown` | `chatbot/documents/knowledge_base/validators.py` | Upload types `kb_admin.py` accepts: the ones text can be extracted from. |

## Tuning Recipes

### "Reduce LLM cost"

Trim the retrieved context the LLM sees. The levers are `MAX_CONTEXT_DOCS`,
`PAGE_CONTEXT_CHARS` and the chunk size; smaller chunks lower the context payload:

```python
# chatbot/bookstack/chunking.py
DEFAULTS = {'chunk_size': 500, 'overlap': 80, 'min_size': 60}
```

### "Improve precision on a small wiki"

Larger chunks keep more context together and let the LLM answer multi-paragraph
questions with fewer chunks in the prompt:

```python
# chatbot/bookstack/chunking.py
DEFAULTS = {'chunk_size': 1200, 'overlap': 200, 'min_size': 100}
```

After changing the wiki chunking, rebuild the BookStack index:

```bash
docker compose --env-file .env -f docker/docker-compose.yml exec chatbot python resync.py --full-resync
```

After changing the upload chunking, reindex the uploads:

```bash
python3 scripts/kb_admin.py index rebuild --force
```

### "Handle a large wiki (>10k pages)"

There is no supported path for this today. SQLite FTS5 keeps working, but ingestion and
rebuilds get slow, and moving to Postgres means rewriting the four knowledge-base
services rather than configuring anything: no backend interface exists to implement.
See [ARCHITECTURE.md](ARCHITECTURE.md) for the trade-off table and what the rewrite
involves.
