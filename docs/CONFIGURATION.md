# Configuration Reference

Every environment variable the chatbot reads, in the order it appears in `.env.example`.

The Required column says whether the software insists. Several variables that are
**not** required have defaults you should still override; those are called out in the
Purpose column and repeated in the checklist in [SECURITY.md](SECURITY.md).

## Core

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `SECRET_KEY` | No, but set it | `chatbot-dev-secret-change-in-production` | Flask session signing key. `chatbot/config.py` falls back to that literal and the app starts silently, so an unset key means sessions are signed with a value published in this repository. Generate with `openssl rand -hex 32`. |
| `TZ` | No | `UTC` | Timezone for log timestamps and containers. Use IANA names (e.g. `Europe/Berlin`). |
| `FLASK_ENV` | No | `production` | `production` or `development`. Development enables debug pages and verbose tracebacks. |
| `FLASK_DEBUG` | No | `false` | Enable Flask debug mode. With it on, Flask serves tracebacks to the client and `/debug` returns the URL map instead of a 403, so leave it off outside development. |
| `LOG_LEVEL` | No | `INFO` | One of `DEBUG`, `INFO`, `WARNING`, `ERROR`. |

## LLM Providers

At least one provider must be configured. `create_llm_provider()` in
`chatbot/llm/factory.py` tries Azure first and Ollama second, and raises rather than
falling back further when neither answers.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `AZURE_OPENAI_API_KEY` | If using Azure | none | Azure OpenAI API key. The provider is only considered when this **and** `AZURE_OPENAI_ENDPOINT` are set. |
| `AZURE_OPENAI_ENDPOINT` | If using Azure | none | Full endpoint URL, e.g. `https://my-resource.openai.azure.com/`. |
| `AZURE_OPENAI_API_VERSION` | No | `2025-01-01-preview` | API version. |
| `AZURE_OPENAI_DEPLOYMENT_NAME` | If using Azure | `gpt-4o-mini` | Name of the deployment in Azure (not the model name). |
| `OLLAMA_BASE_URL` | If using Ollama | `http://host.docker.internal:11434` | URL of an Ollama instance reachable from the chatbot container. |
| `ENABLE_OLLAMA_FALLBACK` | No | `false` | Set to `true` to allow Ollama as a fallback when other providers are unset. Disabled by default for safety. |

## BookStack Integration

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `BOOKSTACK_EXTERNAL_URL` | Yes | `http://localhost:6875` | Public URL of BookStack. Used in widget source citations. |
| `BOOKSTACK_PORT` | No | `6875` | Host port that BookStack is published on. |
| `BOOKSTACK_APP_KEY` | Yes (BookStack) | none | BookStack's APP_KEY. Generate once and pin. See `.env.example` for the command. |
| `BOOKSTACK_TOKEN_ID` | Yes | none | BookStack API token ID. Create in BookStack: My Account → API Tokens. |
| `BOOKSTACK_TOKEN_SECRET` | Yes | none | BookStack API token secret. Shown only once at creation time. |
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
| `CHATBOT_SYSTEM_PROMPT` | No | see below | Replaces the widget's default system prompt wholesale. The default is the literal in `chatbot/chat/widget_service.py`, which tells the model to use both sources, cite them briefly, say so when the sources do not answer, and reply in the user's language. |
| `DATABASE_PATH` | No | `/app/data/chatbot.db` in the container | SQLite file. Set in `docker-compose.yml`; without it `chatbot/config.py` falls back to `chatbot/data/chatbot.db` next to the code. The admin CLI reads the same variable. |
| `BOOKSTACK_API_URL` | No | `http://bookstack:80` | Where the chatbot reaches the BookStack API. Set in `docker-compose.yml` to the Docker-internal hostname; `BOOKSTACK_EXTERNAL_URL` is the separate public URL used in citations. |

## Access Control

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `ALLOWED_VPN_IPS` | No, but set it | empty | Comma-separated CIDRs allowed to reach `/chat/api/*` and `/webhook/bookstack`. Example: `10.0.0.0/8,192.168.0.0/16`. **Empty means allow all**, logged once as a warning at startup. A non-empty value with no parseable CIDR denies everything instead. |
| `IP_ACCESS_CONTROL` | No | `true` | Set to `false` to bypass the allow-list (development only). |
| `RATE_LIMIT_PER_MINUTE` | No | `30` | Sliding-window per-IP limit on `/chat/api/widget`. Read at decoration time; a non-integer value logs a warning and falls back to 30. |

## Hidden / Advanced

These knobs live in Python, not env vars. Edit the listed file to change.

| Setting | Default | Where | Purpose |
|---|---|---|---|
| `BookStackChunkingService.DEFAULTS['chunk_size']` | `800` (words) | `chatbot/bookstack/chunking.py` | Target chunk size for indexing. |
| `BookStackChunkingService.DEFAULTS['overlap']` | `150` (words, 19 % of `chunk_size`) | same | Overlap between consecutive chunks. Must be smaller than `chunk_size`; the constructor raises otherwise. |
| `BookStackChunkingService.DEFAULTS['min_size']` | `80` (words) | same | Chunks smaller than this are merged forward. |
| `Config.MAX_CONTENT_LENGTH` | `16 MB` | `chatbot/config.py` | Flask's request-body cap. |
| `MAX_FILE_SIZE` | `20 MB` | `chatbot/documents/knowledge_base/validators.py` | Knowledge-base upload cap. The lower Flask limit wins for anything going over HTTP. |
| `ALLOWED_EXTENSIONS` | `pdf, docx, doc, txt, md, csv, xlsx, xls` | same file | Accepted upload types. |

## Tuning Recipes

### "Reduce LLM cost"

Trim the retrieved context the LLM sees. There is no env knob for this today;
the simplest lever is the chunking config: fewer, smaller chunks lower the
total context payload:

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

After changing chunking parameters, re-run the index:

```bash
PYTHONPATH=chatbot python3 scripts/kb_admin.py index rebuild --force
```

The CLI runs on the host only and needs `PYTHONPATH`; see
[KB_ADMIN_CLI.md](KB_ADMIN_CLI.md). These knobs govern **BookStack** chunking only;
uploaded documents are chunked by
`chatbot/documents/knowledge_base/services/chunking.py`.

### "Handle a large wiki (>10k pages)"

There is no supported path for this today. SQLite FTS5 keeps working, but ingestion and
rebuilds get slow, and moving to Postgres means rewriting the four knowledge-base
services rather than configuring anything: no backend interface exists to implement.
See [ARCHITECTURE.md](ARCHITECTURE.md) for the trade-off table and what the rewrite
involves.
