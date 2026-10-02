# BookStack RAG Chatbot

![Version](https://img.shields.io/badge/version-0.6.0-blue)
![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python)
![Docker](https://img.shields.io/badge/Docker-20.10%2B-blue?logo=docker)
![BookStack](https://img.shields.io/badge/BookStack-25.07-orange)
![CI](https://github.com/fidpa/bookstack-rag-chatbot/actions/workflows/lint.yml/badge.svg)
![Status](https://img.shields.io/badge/status-production-brightgreen)
![Last Commit](https://img.shields.io/github/last-commit/fidpa/bookstack-rag-chatbot)

A Retrieval-Augmented Generation (RAG) chatbot for [BookStack](https://www.bookstackapp.com/) wikis. It indexes wiki content via webhooks, puts a chat bubble on every BookStack page through an embedded widget, and answers from the wiki using Azure OpenAI or a local Ollama model.

Self-hosted wikis fill up with content that keyword search cannot find, and a public LLM has never seen any of it. Visitors give up searching, and the same questions come back in team chat. This repository is extracted from a setup that has run next to a production BookStack instance since October 2025, with the company-specific parts removed. The code here has been reworked since (see the changelog), so the figures under "Reported Figures" describe that deployment, not this release.

## Features

- **Hybrid retrieval over two indexes**: seven SQLite FTS5 strategies (title and tags, exact phrase, AND, OR, proximity, chunk-level, fuzzy) run over an independent knowledge base of uploaded documents; the BookStack content is searched by keyword (OR) at page and chunk level. A document that several strategies find gets a fusion bonus.
- **Two LLM providers behind one interface**: `LLMProvider` in `chatbot/llm/base.py`, with Azure OpenAI and Ollama implementations. The factory picks by which credentials are present.
- **Embedded JS widget**: one `<script>` snippet in BookStack's custom-head setting, and the chat bubble appears on every page.
- **Webhook sync, no cron**: 15 BookStack events (page, chapter, book, recycle-bin restore, changed permissions) reach the chatbot, which reads the item back a couple of seconds later and moves the index as the wiki is edited: creations, edits, moves, deletions, restores and permission changes. `chatbot/resync.py --full-resync` rebuilds the index where webhooks were missed.
- **IP allow-list and per-IP rate limit**: both are decorators on the widget endpoint in `chatbot/utils/rate_limiter.py` and run before any LLM call. The limit is a sliding window, 30 requests per minute by default.
- **Admin CLI**: `scripts/kb_admin.py` carries five subcommands (`documents`, `bulk`, `index`, `stats`, `maintenance`) for knowledge-base documents, reindexing, statistics and maintenance.
- **Hardened Docker stack**: `no-new-privileges:true` and a healthcheck on all three services, CPU and memory limits on the chatbot container.

## ⚠️ Known Limitations

> - ❌ **Stock BookStack does not sign its webhooks** (checked against v25.07). Authenticity rests on the IP allow-list, which checks the connecting address; behind a reverse proxy set `TRUSTED_PROXY_HOPS=1` and keep port 8888 unreachable around the proxy (see [docs/SECURITY.md](docs/SECURITY.md)). The HMAC-SHA256 check in `chatbot/bookstack/webhooks.py` exists and switches on with `BOOKSTACK_WEBHOOK_SECRET`, but nothing sends the `X-BookStack-Signature` header until a custom plugin or a later BookStack release does.
> - ❌ **An empty `ALLOWED_VPN_IPS` allows every source**, and `.env.example` ships it empty. Fill it in before the chatbot is reachable from anywhere but your own machine.
> - ❌ **No storage abstraction.** SQLite access lives in four service classes under `chatbot/documents/knowledge_base/services/` (storage, indexing, search, context). There is no backend interface to implement, so moving to Postgres and `pgvector` means rewriting those four, not plugging into a seam. Only the LLM layer is abstracted today.
> - ❌ **SQLite FTS5 is single-writer.** The deployment behind this repository indexes about 150 pages. The 10 000-page figure quoted in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) is an estimate from FTS5's behaviour, not a measured ceiling.
> - ❌ **Single-tenant.** One deployment serves one BookStack instance.
> - ❌ **BookStack's permissions do not apply to answers.** The chatbot indexes everything the API token's user can see and answers every client that passes the IP allow-list from it, without knowing who is asking. A page that only some roles may open in BookStack can be quoted to anyone who reaches the chatbot. Create the token for a dedicated BookStack user whose role sees only what everyone with chatbot access may read, never for an administrator ([docs/SETUP.md](docs/SETUP.md), [docs/SECURITY.md](docs/SECURITY.md)).
> - ⚠️ **Prompt injection is made harder, not prevented.** Wiki pages, uploaded documents and the page text the widget sends are fenced as data with a random tag and the model is told not to follow them, but a model can still be steered by text that someone who may edit the wiki planted there, and a planted false fact reads like any other. Treat write access to the wiki as influence over the answers ([docs/SECURITY.md](docs/SECURITY.md#prompt-injection-harder-not-prevented)).
> - ⚠️ **Webhook syncs are delayed and best-effort.** BookStack sends create, move and sort events from inside its own database transaction, so the chatbot queues each event, reads BookStack back about two seconds later and tries again for roughly 20 seconds while the item is not visible yet or BookStack does not answer (longer if requests hang until their timeout, or while BookStack's API rate limit makes a request wait for the next minute; checked against BookStack 25.07.3). A job that still fails is logged (`gave up`) and left to the next full resync; jobs still queued when the container stops are lost ([docs/BOOKSTACK_WEBHOOKS.md](docs/BOOKSTACK_WEBHOOKS.md)).
> - ⚠️ **Ollama fallback is off by default** (`ENABLE_OLLAMA_FALLBACK=false`), so a missing Azure key fails loudly instead of quietly reaching for an unhardened local model. Turn it on explicitly.
> - ⚠️ **Some internal docstrings, comments and log messages are still in German**, a legacy of the original production deployment. They sit in the upload side of `chatbot/documents/knowledge_base/` (storage and the query analyzer). Everything a visitor sees, the env vars, the CLI and the rest of the code are English. The German stopword and intent lists in `query_processor/constants.py` are language data and stay. PRs translating the rest are welcome.

## Quick Start

You need: Docker 20.10+, ~3 GB free RAM, and 5 minutes.

```bash
# 1. Clone
git clone https://github.com/fidpa/bookstack-rag-chatbot.git
cd bookstack-rag-chatbot

# 2. Configure
cp .env.example .env
# Open .env and set: SECRET_KEY, BOOKSTACK_DB_PASSWORD, MYSQL_ROOT_PASSWORD,
# BOOKSTACK_APP_KEY (see comments in the file), ALLOWED_VPN_IPS,
# and ONE LLM provider key.

# 3. Boot the stack (run everything from the repository root; --env-file is
#    required, because Compose reads ".env" from docker/, not from here)
docker compose --env-file .env -f docker/docker-compose.yml up -d
# Wait ~30 s for BookStack to initialise its database.

# 4. Create the BookStack admin account
# Open http://localhost:6875 in your browser.
# Sign in as admin@admin.com with the password "password" (BookStack's default)
# and change both immediately. Then create the API token for a dedicated read-only
# user, not the admin, whose token would put restricted pages into every answer
# (docs/SETUP.md, step 5): Settings → Users → (that user) → API Tokens → Create Token.
# Paste the Token ID and Secret into .env as BOOKSTACK_TOKEN_ID / BOOKSTACK_TOKEN_SECRET.

# 5. Recreate the chatbot so it picks up the new tokens ("restart" would keep
#    the old, empty ones)
docker compose --env-file .env -f docker/docker-compose.yml up -d chatbot

# 6. Load the demo content (the fictional Acme Inc. knowledge base).
# The loader runs on the host and reads its credentials from the environment.
# It creates a book and pages, which the read-only token from step 4 may not:
# put an admin's token into SAMPLES_TOKEN_ID / SAMPLES_TOKEN_SECRET in .env
# (My Account → Access & Security → API Tokens) and delete it afterwards.
# The subshell keeps .env out of your shell: exported variables would win over
# later edits of .env the next time you run Compose from it.
# Debian 12 and Ubuntu 24.04 refuse pip here; use: sudo apt install python3-requests
pip install requests
(set -a; . ./.env; set +a; python3 samples/load-samples.py)

# 7. Index it. Webhooks keep the index current from here on once they are
# set up (docs/BOOKSTACK_WEBHOOKS.md); content that existed before needs one
# full sync.
docker compose --env-file .env -f docker/docker-compose.yml exec chatbot python resync.py --full-resync

# 8. Paste bookstack-integration/widget.html into BookStack's
# Settings → Customization → Custom HTML Head Content, then reload a page.
# The chat bubble sits in the lower-right corner.
# Try: "What are Acme's core working hours?"
```

## Architecture

```
                ┌──────────────────────────────────────────────┐
                │                Visitor / Employee            │
                │  (browser, internal LAN or VPN)              │
                └──────────────┬───────────────────────────────┘
                               │ HTTPS (reverse proxy terminates TLS)
                               ▼
                ┌──────────────────────────────────────────────┐
                │   BookStack 25.07  (port 6875)                │
                │   ┌────────────────────────────────────────┐ │
                │   │   widget.html  (custom-head injection) │ │
                │   └──────────────┬─────────────────────────┘ │
                └──────────────────┼───────────────────────────┘
                                   │ POST /chat/api/widget
                                   ▼
                ┌──────────────────────────────────────────────┐
                │   chatbot backend  (Flask, port 8888)         │
                │   • IP allow-list + per-IP rate limit          │
                │   • Hybrid retrieval (SQLite FTS5)             │
                │   • LLM factory  ── Azure / Ollama             │
                └────┬──────────────────────────────┬───────────┘
                     │ webhooks (15 events)         │ LLM call
                     ▼                              ▼
              ┌──────────────────┐         ┌──────────────────┐
              │ BookStack API    │         │   LLM provider   │
              │ /api/pages, …    │         │   (cloud / local)│
              └──────────────────┘         └──────────────────┘
```

The chatbot owns one SQLite database (`/app/data/chatbot.db`) with two parallel indexes:

- **`bookstack_*` tables**: every BookStack page, kept in sync via webhooks.
- **`kb_*` tables**: uploaded documents (PDF, DOCX, Markdown, text), managed via the admin CLI.

Both are searched at query time, and the top candidates go to the LLM as context for the answer.

## Use Cases

**Perfect for:**

- 🏢 **Internal company wikis**: Q&A over your team's documentation
- 🎓 **Customer-facing docs portals**: an "ask the docs" widget for product help
- 👋 **Employee onboarding**: new hires ask the bot before pinging a human
- 📚 **Self-hosted knowledge bases** for SMBs, agencies, research labs

**Not recommended for:**

- 🌍 **Public, unauthenticated chatbots**: the IP allow-list is the only auth layer, so a public-internet deployment needs an auth proxy in front of it
- 🏬 **Multi-tenant SaaS**: single-tenant by design
- 📖 **Corpora well past a few thousand pages**: see the SQLite limitation above
- 🧠 **Hallucination-sensitive contexts** (medical or legal advice given to end users): the LLM still hallucinates. This retrieves from your wiki; it does not certify the answer.

## Key Concepts

### Hybrid retrieval, not vector search

Embeddings are not the primary retrieval mechanism here. Seven FTS5 strategies (title and tags, exact phrase, AND, OR, proximity, chunk-level, fuzzy) run over the uploaded documents, and the BookStack content is searched by keyword (OR) at page and chunk level; the result sets are fused in `chatbot/documents/knowledge_base/services/hybrid_search/fusion.py`: a document's score is multiplied by `1 + 0.5 * n` for the `n` strategies that found it, and the top candidates are handed to the LLM.

Two reasons for that choice. Retrieval stays inside the SQLite process, so there is no network hop before the LLM call and no second data service to operate or back up. And for internal docs in one language with consistent vocabulary, BM25 and FTS5 hold up against dense retrieval; the fusion covers the queries that only one strategy would have found. Where that stops being true, multilingual corpora and semantic questions, is written up in [docs/RAG_DESIGN.md](docs/RAG_DESIGN.md).

### The storage layer is SQLite all the way down

The knowledge-base code is split into four services (storage, indexing, search, context), which keeps the SQL in a small number of files. It is a separation of concerns, not a backend seam: none of the four sits behind an interface, and every one of them writes FTS5 SQL directly. A Postgres or `pgvector` backend is a rewrite of those four classes, and extracting a backend interface is step zero. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) carries the trade-off table behind the SQLite decision.

### Provider selection

The factory in `chatbot/llm/factory.py` picks by what is configured:

1. **Azure OpenAI**, when both `AZURE_OPENAI_API_KEY` and `AZURE_OPENAI_ENDPOINT` are set. There is no network probe; an unreachable endpoint shows up as a failed answer. This is what the production deployment runs.
2. **Ollama**, only when `ENABLE_OLLAMA_FALLBACK=true`, the local instance answers and the model (`OLLAMA_MODEL`, default `mistral:latest`) is pulled.

If neither is available, the widget answers with a notice that no AI service is available and the operator log names the missing piece; nothing degrades silently. Switching providers is an env-var change and a container restart.

### Widget-only architecture

The chatbot has no UI of its own: no login, no user database, no admin web interface. Everything user-facing happens inside the BookStack page through the embedded widget. The chatbot does not know who is asking: it trusts whatever IP got past the allow-list and the reverse proxy, and it holds no user database.

That is deliberate: one fewer system to harden and one fewer login screen. The cost is stated in the limitations above: everything the chatbot itself enforces is an IP allow-list, and **BookStack's permissions are not applied to its answers**. Access is decided once, when the index is built, by what the API token's user can see.

## Repository Structure

```
bookstack-rag-chatbot/
├── README.md                     # You are here
├── LICENSE                       # MIT
├── CHANGELOG.md
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
├── SECURITY.md
├── .env.example                  # Copy to .env and fill in
├── .gitignore
├── pytest.ini
├── ruff.toml
├── .github/workflows/
│   ├── lint.yml                  # ruff + black + mypy, pytest, yamllint
│   └── release.yml               # Auto-release on git tag
│
├── chatbot/                      # Flask RAG backend
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app.py                    # Flask entrypoint
│   ├── config.py
│   ├── version.py                # Release version (the README badge is the other copy)
│   ├── startup_migrations.py     # Creates and repairs the schema on every start
│   ├── resync.py                 # Full rebuild of the BookStack index
│   ├── llm/                      # LLMProvider interface + Azure/Ollama
│   ├── bookstack/                # BookStack API client + webhook handlers
│   ├── chat/                     # Widget endpoint, session, prompt building
│   ├── documents/                # RAG layer + knowledge-base management
│   ├── utils/                    # Rate limiter, IP allow-list, DB helpers, chunking
│   ├── static/                   # favicon
│   └── templates/                # Standalone chat page, error pages
│
├── bookstack-integration/
│   └── widget.html               # Paste into BookStack → Settings → Custom HTML head
│
├── docker/
│   ├── docker-compose.yml        # 3-service stack: bookstack, bookstack_db, chatbot
│   ├── mariadb-optimized.cnf     # MariaDB tuning for small instances
│   └── nginx-example.conf        # Reverse proxy for BookStack and the widget API
│
├── samples/                      # Acme Inc. fictional knowledge base
│   ├── README.md
│   ├── acme-*.md                 # 5 sample documents (CC0)
│   └── load-samples.py           # One-shot loader script
│
├── scripts/
│   ├── kb_admin.py               # Knowledge-base admin CLI
│   └── init_kb_schema.py         # Create (or --force recreate) the kb_* tables
│
├── tests/                        # pytest, no BookStack or LLM needed
│   ├── README.md
│   ├── conftest.py               # Temporary database, fake BookStack API
│   └── test_*.py
│
└── docs/                         # Detailed documentation (DIATAXIS)
    ├── README.md
    ├── SETUP.md
    ├── ARCHITECTURE.md
    ├── RAG_DESIGN.md
    ├── WIDGET_INTEGRATION.md
    ├── BOOKSTACK_WEBHOOKS.md
    ├── SECURITY.md
    ├── KB_ADMIN_CLI.md
    ├── CONFIGURATION.md
    └── TROUBLESHOOTING.md
```

## Component Overview

| Component | Purpose | Technology |
|-----------|---------|------------|
| `chatbot/app.py` | Flask HTTP entrypoint, route registry, health endpoint | Python 3.11, Flask |
| `chatbot/llm/base.py` | `LLMProvider` abstract base class | `abc` |
| `chatbot/llm/factory.py` | Selects and instantiates a provider | Factory function |
| `chatbot/llm/providers/` | Azure OpenAI, Ollama implementations | `openai`, `requests` |
| `chatbot/bookstack/api_client.py` | BookStack REST client | `requests` |
| `chatbot/bookstack/webhooks.py` | Webhook endpoint for 15 BookStack events; deletions at once, the rest queued | Flask blueprint |
| `chatbot/bookstack/webhook_worker.py` | Runs the queued webhook syncs after the response, in order, with retries | `threading` |
| `chatbot/bookstack/sync_service.py` | Index schema, sync walk, deletes, prune | SQLite FTS5 |
| `chatbot/utils/text_chunking.py` | Chunking for wiki pages and uploads | Sentence- and line-aware sliding window |
| `chatbot/documents/knowledge_base/` | KB ingestion (PDF/DOCX/MD), FTS5 indexing, hybrid search | `pypdfium2`, `pypdf`, `python-docx`, SQLite FTS5 |
| `chatbot/chat/routes/api.py` | Widget query endpoint, guarded by allow-list and rate limit | Flask |
| `chatbot/chat/widget_service.py` | Prompt assembly, in-memory conversation sessions | Flask |
| `chatbot/chat/prompt_framing.py` | Fences the context as data and adds the rule that says so to every system prompt | `secrets`, `re` |
| `chatbot/utils/rate_limiter.py` | IP allow-list, sliding-window rate limit | `ipaddress`, in-memory store |
| `bookstack-integration/widget.html` | Embeddable chat bubble | Vanilla JS, no build step |
| `scripts/kb_admin.py` | Admin CLI (documents, bulk, index, stats, maintenance) | `argparse` subcommands |

## Documentation

| Document | Description |
|----------|-------------|
| [SETUP.md](docs/SETUP.md) | Full installation and first-run guide |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Design decisions and trade-offs |
| [RAG_DESIGN.md](docs/RAG_DESIGN.md) | Chunking, FTS5 multi-strategy retrieval, and score fusion |
| [WIDGET_INTEGRATION.md](docs/WIDGET_INTEGRATION.md) | Embedding the widget into BookStack (or any other site) |
| [BOOKSTACK_WEBHOOKS.md](docs/BOOKSTACK_WEBHOOKS.md) | The 15 webhook events and how they map to index operations |
| [SECURITY.md](docs/SECURITY.md) | Hardening guide for production deployments |
| [KB_ADMIN_CLI.md](docs/KB_ADMIN_CLI.md) | Admin CLI command reference |
| [CONFIGURATION.md](docs/CONFIGURATION.md) | Every environment variable explained |
| [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Common issues and fixes |

📚 **Recommended reading order**: SETUP → ARCHITECTURE → RAG_DESIGN → WIDGET_INTEGRATION → SECURITY → TROUBLESHOOTING

## Requirements

| | Minimum | Recommended |
|---|---|---|
| OS | Ubuntu 22.04 LTS | Ubuntu 24.04 LTS |
| Docker | 20.10+ with Compose v2 | latest stable |
| CPU | 1 vCPU | 2 vCPU |
| RAM | 3 GB | 4 GB |
| LLM provider | Azure OpenAI or local Ollama | Azure OpenAI |

CPU and RAM scale with corpus size. The compose file caps the chatbot container at 2 vCPU and 4 GB with a 512 MB reservation; BookStack and MariaDB run without limits.

## Compatibility

**Fully supported:**

- Ubuntu 22.04 / 24.04 LTS, Debian 11 / 12, x86_64 and ARM64
- Raspberry Pi 5 (8 GB) with an external SSD, for small wikis

**Should work** (untested):

- Other systemd-based distros with Docker support
- macOS for development (Docker Desktop)
- Windows 11 + WSL2

## Reported Figures

Reported by the operator of the deployment this repository was extracted from (a small business, running since October 2025 on Azure OpenAI `gpt-4o-mini`), for October 2025 to May 2026. They were not re-measured against this code, and that deployment does not necessarily run this release:

- ~150 wiki pages indexed
- ~25 chat queries per business day
- Median end-to-end response time: 1.8 s (question in the widget to answer rendered)
- Cost: under €10 per month in LLM calls
- Container resource usage: ~250 MB RSS and below 5 % CPU at idle

These numbers describe one deployment on one corpus. They are the order of magnitude to expect, not a benchmark.

## License

MIT, see [LICENSE](LICENSE).

## Author

Marc Allgeier ([@fidpa](https://github.com/fidpa))

**Why I built this**: the off-the-shelf options either wanted our knowledge base uploaded to a third party, or sold themselves as drop-in and arrived as a SaaS bundle. So I built the smallest thing that could work, one Flask service and one SQLite database and one widget, and ran it next to BookStack for a few months. It held up. This repo is that setup.

## See Also

- [step-ca-internal-pki](https://github.com/fidpa/step-ca-internal-pki): internal PKI for trusted HTTPS without browser warnings
- [ubuntu-server-security](https://github.com/fidpa/ubuntu-server-security): security-hardening components for self-hosted servers
- [bash-production-toolkit](https://github.com/fidpa/bash-production-toolkit): logging, alerts, and secure-file utilities used by my other repos

## Credits

Built on top of [BookStack](https://www.bookstackapp.com/) (MIT) and [linuxserver.io's BookStack image](https://docs.linuxserver.io/images/docker-bookstack/) (GPLv3 for the container image, not for the BookStack code).
