# Configuration Reference

Every environment variable the chatbot reads, in the order it appears in `.env.example`.

## Core

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `SECRET_KEY` | Yes | — | Flask session signing key. Generate with `openssl rand -hex 32`. |
| `TZ` | No | `UTC` | Timezone for log timestamps and containers. Use IANA names (e.g. `Europe/Berlin`). |
| `FLASK_ENV` | No | `production` | `production` or `development`. Development enables debug pages and verbose tracebacks. |
| `FLASK_DEBUG` | No | `false` | Enable Flask debug mode. Never set to `true` in production. |
| `LOG_LEVEL` | No | `INFO` | One of `DEBUG`, `INFO`, `WARNING`, `ERROR`. |

## LLM Providers

At least one provider must be configured. Selection precedence: Azure → Ollama.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `AZURE_OPENAI_API_KEY` | If using Azure | — | Azure OpenAI API key. |
| `AZURE_OPENAI_ENDPOINT` | If using Azure | — | Full endpoint URL, e.g. `https://my-resource.openai.azure.com/`. |
| `AZURE_OPENAI_API_VERSION` | No | `2025-01-01-preview` | API version. |
| `AZURE_OPENAI_DEPLOYMENT_NAME` | If using Azure | `gpt-4o-mini` | Name of the deployment in Azure (not the model name). |
| `OLLAMA_BASE_URL` | If using Ollama | `http://host.docker.internal:11434` | URL of an Ollama instance reachable from the chatbot container. |
| `ENABLE_OLLAMA_FALLBACK` | No | `false` | Set to `true` to allow Ollama as a fallback when other providers are unset. Disabled by default for safety. |

## BookStack Integration

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `BOOKSTACK_EXTERNAL_URL` | Yes | `http://localhost:6875` | Public URL of BookStack. Used in widget source citations. |
| `BOOKSTACK_PORT` | No | `6875` | Host port that BookStack is published on. |
| `BOOKSTACK_APP_KEY` | Yes (BookStack) | — | BookStack's APP_KEY. Generate once and pin. See `.env.example` for the command. |
| `BOOKSTACK_TOKEN_ID` | Yes | — | BookStack API token ID. Create in BookStack: My Account → API Tokens. |
| `BOOKSTACK_TOKEN_SECRET` | Yes | — | BookStack API token secret. Shown only once at creation time. |
| `BOOKSTACK_WEBHOOK_SECRET` | No | — | Reserved for a future HMAC layer. Not validated by BookStack v25.07. |

## Database (MariaDB for BookStack)

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `BOOKSTACK_DB_PASSWORD` | Yes | — | Password for the BookStack DB user. |
| `MYSQL_ROOT_PASSWORD` | Yes | — | MariaDB root password. |

## Chatbot

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `CHATBOT_PORT` | No | `8888` | Host port for the chatbot's HTTP API. |

## Access Control

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `ALLOWED_VPN_IPS` | No | empty (allow all) | Comma-separated list of CIDRs allowed to query the chatbot. Example: `10.0.0.0/8,192.168.0.0/16`. |
| `IP_ACCESS_CONTROL` | No | `true` | Set to `false` to bypass the allow-list (development only). |
| `RATE_LIMIT_PER_MINUTE` | No | `30` | Sliding-window per-IP rate limit. |

## Hidden / Advanced

These knobs live in Python, not env vars. Edit the listed file to change.

| Setting | Default | Where | Purpose |
|---|---|---|---|
| `BookStackChunkingService.DEFAULTS['chunk_size']` | `800` (words) | `chatbot/bookstack/chunking.py` | Target chunk size for indexing. |
| `BookStackChunkingService.DEFAULTS['overlap']` | `150` (words ≈ 19 %) | same | Overlap between consecutive chunks. |
| `BookStackChunkingService.DEFAULTS['min_size']` | `80` (words) | same | Chunks smaller than this are merged forward. |
| `Config.MAX_CONTENT_LENGTH` | `16 MB` | `chatbot/config.py` | Max upload size (Flask). |

## Tuning Recipes

### "Reduce LLM cost"

Trim the retrieved context the LLM sees. There is no env knob for this today;
the simplest lever is the chunking config — fewer, smaller chunks lower the
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
python scripts/kb_admin.py index rebuild --force
```

### "Handle a large wiki (>10k pages)"

You'll need to swap SQLite for Postgres+pgvector. SQLite FTS5 still works at this size, but ingestion and rebuilds become slow. See [ARCHITECTURE.md](ARCHITECTURE.md#why-sqlite).
