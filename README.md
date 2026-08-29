# BookStack RAG Chatbot

![Version](https://img.shields.io/badge/version-0.2.0-blue)
![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python)
![Docker](https://img.shields.io/badge/Docker-20.10%2B-blue?logo=docker)
![BookStack](https://img.shields.io/badge/BookStack-25.07-orange)
![CI](https://github.com/fidpa/bookstack-rag-chatbot/actions/workflows/lint.yml/badge.svg)
![Status](https://img.shields.io/badge/status-production-brightgreen)
![Last Commit](https://img.shields.io/github/last-commit/fidpa/bookstack-rag-chatbot)

A Retrieval-Augmented Generation (RAG) chatbot for [BookStack](https://www.bookstackapp.com/) wikis. It indexes wiki content via webhooks, puts a chat bubble on every BookStack page through an embedded widget, and answers from the wiki using Azure OpenAI or a local Ollama model.

Self-hosted wikis fill up with content that keyword search cannot find, and a public LLM has never seen any of it. Visitors give up searching, and the same questions come back in team chat. This repository is the setup that has run next to a production BookStack instance since October 2025, with the company-specific parts removed.

## Features

- **Hybrid retrieval over two indexes**: seven SQLite FTS5 strategies (title and tags, exact phrase, AND, OR, proximity, chunk-level, fuzzy) run against both the BookStack content and an independent knowledge base of uploaded documents. A document that several strategies find gets a fusion bonus.
- **Two LLM providers behind one interface**: `LLMProvider` in `chatbot/llm/base.py`, with Azure OpenAI and Ollama implementations. The factory picks by which credentials are present.
- **Embedded JS widget**: one `<script>` snippet in BookStack's custom-head setting, and the chat bubble appears on every page.
- **Webhook sync, no cron**: 13 BookStack events (page, chapter, book) reach `ContentSyncService` and move the index as the wiki is edited, deletions included. `chatbot/resync.py --full-resync` rebuilds the index where webhooks were missed.
- **IP allow-list and per-IP rate limit**: both are decorators on the widget endpoint in `chatbot/utils/rate_limiter.py` and run before any LLM call. The limit is a sliding window, 30 requests per minute by default.
- **Admin CLI**: `scripts/kb_admin.py` carries five subcommands (`documents`, `bulk`, `index`, `stats`, `maintenance`) for knowledge-base documents, reindexing, statistics and maintenance.
- **Hardened Docker stack**: `no-new-privileges:true` and a healthcheck on all three services, CPU and memory limits on the chatbot container.

## ⚠️ Known Limitations

> - ❌ **Stock BookStack does not sign its webhooks** (checked against v25.07). Authenticity rests on the IP allow-list, so your reverse proxy has to strip spoofed source IPs. The HMAC-SHA256 check in `chatbot/bookstack/webhooks.py` exists and switches on with `BOOKSTACK_WEBHOOK_SECRET`, but nothing sends the `X-BookStack-Signature` header until a custom plugin or a later BookStack release does.
> - ❌ **An empty `ALLOWED_VPN_IPS` allows every source**, and `.env.example` ships it empty. Fill it in before the chatbot is reachable from anywhere but your own machine.
> - ❌ **No storage abstraction.** SQLite access lives in four service classes under `chatbot/documents/knowledge_base/services/` (storage, indexing, search, context). There is no backend interface to implement, so moving to Postgres and `pgvector` means rewriting those four, not plugging into a seam. Only the LLM layer is abstracted today.
> - ❌ **SQLite FTS5 is single-writer.** The deployment behind this repository indexes about 150 pages. The 10 000-page figure quoted in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) is an estimate from FTS5's behaviour, not a measured ceiling.
> - ❌ **Single-tenant.** One deployment serves one BookStack instance.
> - ⚠️ **Ollama fallback is off by default** (`ENABLE_OLLAMA_FALLBACK=false`), so a missing Azure key fails loudly instead of quietly reaching for an unhardened local model. Turn it on explicitly.
> - ⚠️ **Some internal docstrings and comments are still in German**, a legacy of the original production deployment. The user-facing surface (README, env vars, CLI, log messages) is English, with two exceptions: `chatbot/llm/factory.py` raises two German `ValueError` strings that reach the operator log. PRs translating internals are very welcome.

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

# 3. Boot the stack
docker compose -f docker/docker-compose.yml up -d
# Wait ~30 s for BookStack to initialise its database.

# 4. Create the BookStack admin account
# Open http://localhost:6875 in your browser.
# Default first-run credentials are printed by BookStack on first boot;
# change them immediately. Then go to: My Account → API Tokens → Create Token.
# Paste the Token ID and Secret into .env as BOOKSTACK_TOKEN_ID / BOOKSTACK_TOKEN_SECRET.

# 5. Restart the chatbot so it picks up the new tokens
docker compose -f docker/docker-compose.yml restart chatbot

# 6. Load the demo content (the fictional Acme Inc. knowledge base).
# The loader runs on the host and reads its credentials from the environment.
pip install requests
set -a; . ./.env; set +a
python3 samples/load-samples.py

# 7. Open BookStack again. The chat bubble sits in the lower-right corner.
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
                     │ webhooks (13 events)         │ LLM call
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

Embeddings are not the primary retrieval mechanism here. Seven FTS5 queries run against the same index (title and tags, exact phrase, AND, OR, proximity, chunk-level, fuzzy), and their result sets are fused in `chatbot/documents/knowledge_base/services/hybrid_search/fusion.py`: a document's score is multiplied by `1 + 0.5 * n` for the `n` strategies that found it, and the top candidates are handed to the LLM.

Two reasons for that choice. Retrieval stays inside the SQLite process, so there is no network hop before the LLM call and no second data service to operate or back up. And for internal docs in one language with consistent vocabulary, BM25 and FTS5 hold up against dense retrieval; the fusion covers the queries that only one strategy would have found. Where that stops being true, multilingual corpora and semantic questions, is written up in [docs/RAG_DESIGN.md](docs/RAG_DESIGN.md).

### The storage layer is SQLite all the way down

The knowledge-base code is split into four services (storage, indexing, search, context), which keeps the SQL in a small number of files. It is a separation of concerns, not a backend seam: none of the four sits behind an interface, and every one of them writes FTS5 SQL directly. A Postgres or `pgvector` backend is a rewrite of those four classes, and extracting a backend interface is step zero. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) carries the trade-off table behind the SQLite decision.

### Provider selection

The factory in `chatbot/llm/factory.py` picks by what is configured:

1. **Azure OpenAI**, when both `AZURE_OPENAI_API_KEY` and `AZURE_OPENAI_ENDPOINT` are set and the endpoint answers. This is what the production deployment runs.
2. **Ollama**, only when `ENABLE_OLLAMA_FALLBACK=true` and the local instance answers.

If neither is available, the request fails with an error that names the missing piece, rather than degrading silently. Switching providers is an env-var change and a container restart.

### Widget-only architecture

The chatbot has no UI of its own: no login, no user database, no admin web interface. Everything user-facing happens inside the BookStack page through the embedded widget, which means **BookStack owns user identity and access control**. The chatbot trusts whatever IP and session got past BookStack and the reverse proxy.

That is deliberate. One fewer system to harden, one fewer login screen, and one source of truth for who can see what. The cost is stated in the limitations above: everything the chatbot itself enforces is an IP allow-list.

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
├── .github/workflows/
│   ├── lint.yml                  # ruff + black + mypy + shellcheck + yamllint
│   └── release.yml               # Auto-release on git tag
│
├── chatbot/                      # Flask RAG backend
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app.py                    # Flask entrypoint
│   ├── config.py
│   ├── startup_migrations.py     # Schema migration runner
│   ├── llm/                      # LLMProvider interface + Azure/Ollama
│   ├── bookstack/                # BookStack API client + webhook handlers
│   ├── chat/                     # Widget endpoint, session, prompt building
│   ├── documents/                # RAG layer + knowledge-base management
│   ├── utils/                    # Rate limiter, IP allow-list, DB helpers, timezone
│   ├── static/                   # CSS / JS (loaded by Flask templates)
│   └── templates/                # Jinja templates
│
├── bookstack-integration/        # Drop-in BookStack assets
│   ├── widget.html               # Paste into BookStack → Settings → Custom HTML head
│   ├── api_client.py             # Reference API client (also used in tests)
│   └── theme-functions.php       # Optional theme hook
│
├── docker/
│   ├── docker-compose.yml        # 3-service stack: bookstack, bookstack_db, chatbot
│   ├── mariadb-optimized.cnf     # MariaDB tuning for small instances
│   └── nginx-example.conf        # Optional reverse-proxy template
│
├── samples/                      # Acme Inc. fictional knowledge base
│   ├── README.md
│   ├── acme-*.md                 # 5 sample documents (CC0)
│   └── load-samples.py           # One-shot loader script
│
├── scripts/
│   ├── kb_admin.py               # Knowledge-base admin CLI
│   └── init_kb_schema.py         # First-time schema init
│
├── tests/
│   ├── README.md
│   ├── test_bookstack_api.py
│   └── test_chunking_integration.py
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
| `chatbot/bookstack/webhooks.py` | Webhook endpoint for 13 BookStack events | Flask blueprint |
| `chatbot/bookstack/chunking.py` | Chunking strategy for wiki pages | Sentence-aware sliding window |
| `chatbot/documents/knowledge_base/` | KB ingestion (PDF/DOCX/MD), FTS5 indexing, hybrid search | `pypdfium2`, `pypdf`, `python-docx`, SQLite FTS5 |
| `chatbot/chat/routes/api.py` | Widget query endpoint, guarded by allow-list and rate limit | Flask |
| `chatbot/chat/widget_service.py` | Prompt assembly and session handling | Flask |
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
| [BOOKSTACK_WEBHOOKS.md](docs/BOOKSTACK_WEBHOOKS.md) | The 13 webhook events and how they map to index operations |
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

## Real-World Results

Measured on the production deployment at a small business, running since October 2025 on Azure OpenAI `gpt-4o-mini`:

- ~150 wiki pages indexed
- ~25 chat queries per business day
- Median end-to-end response time: 1.8 s (question in the widget to answer rendered)
- No index rebuild has been needed since the deployment went live
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
