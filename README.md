# BookStack RAG Chatbot

![Version](https://img.shields.io/badge/version-0.1.4-blue)
![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python)
![Docker](https://img.shields.io/badge/Docker-20.10%2B-blue?logo=docker)
![BookStack](https://img.shields.io/badge/BookStack-25.07-orange)
![CI](https://github.com/fidpa/bookstack-rag-chatbot/actions/workflows/lint.yml/badge.svg)
![Status](https://img.shields.io/badge/status-production-brightgreen)
![Last Commit](https://img.shields.io/github/last-commit/fidpa/bookstack-rag-chatbot)

A production-ready Retrieval-Augmented Generation (RAG) chatbot for [BookStack](https://www.bookstackapp.com/) wikis. It indexes wiki content via webhooks, lets users ask questions inside a small embedded widget, and answers from the wiki using Azure OpenAI or a local Ollama model.

**The Problem**: Self-hosted wikis (BookStack, Wiki.js, Outline, Confluence Server) accumulate hundreds of pages and great content — but their full-text search is keyword-only, and a public LLM has never seen your internal documentation. Visitors give up searching, and your team answers the same questions in chat over and over. After integrating a RAG-backed chatbot into a production wiki running for months, I extracted the entire setup into this repository.

## Features

- **Hybrid RAG** — SQLite FTS5 keyword retrieval with multi-strategy search (title, exact phrase, AND, OR, proximity, chunk-level, fuzzy) and score fusion, over **both** the BookStack content and an independent knowledge base of uploaded documents
- **Multi-provider LLM factory** — Azure OpenAI and Ollama through a single interface; switch by changing one env var
- **Embedded JS widget** — drop one `<script>` snippet into BookStack's custom-head settings and you get a chat bubble on every page
- **Real-time sync** — 13 BookStack webhook events keep the RAG index in lock-step with wiki edits, with no scheduled cron
- **IP-based access control + rate limiting** — sliding-window per-IP limits, allow-list enforced before any LLM call
- **Admin CLI** — `scripts/kb_admin.py` for adding/removing knowledge-base documents, inspecting the index, and running health checks
- **Hardened Docker stack** — `no-new-privileges:true`, explicit CPU/RAM limits, healthchecks on every service
- **Pluggable storage** — uses SQLite FTS5 by default; the indexing layer is abstracted so a Postgres + `pgvector` backend can be dropped in for larger corpora
- **Production-tested** — running in a real SMB wiki since October 2025

## ⚠️ Known Limitations

> - ❌ **BookStack webhooks do not support HMAC signature validation** (as of v25.07). Authenticity is enforced via the IP allow-list — make sure your reverse proxy strips spoofed source IPs.
> - ❌ **SQLite FTS5 is single-writer**. The current setup handles wikis up to ~10 000 pages comfortably. Larger corpora should swap in Postgres + `pgvector`; the indexing layer is abstracted for it (see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)).
> - ❌ **Single-tenant**. One deployment serves one BookStack instance.
> - ⚠️ **Ollama fallback is disabled by default** (`ENABLE_OLLAMA_FALLBACK=false`) to prevent unintentional fallback to an unhardened local model. Enable it explicitly if you want it.
> - ⚠️ **Some internal docstrings and comments are still in German** — a legacy of the original production deployment. The user-facing surface (README, env vars, CLI, log messages) is fully English. PRs translating internals are very welcome.

## Quick Start

You need: Docker 20.10+, ~3 GB free RAM, and 5 minutes.

```bash
# 1. Clone
git clone https://github.com/fidpa/bookstack-rag-chatbot.git
cd bookstack-rag-chatbot

# 2. Configure
cp .env.example .env
# Open .env and set: SECRET_KEY, BOOKSTACK_DB_PASSWORD, MYSQL_ROOT_PASSWORD,
# BOOKSTACK_APP_KEY (see comments in the file), and ONE LLM provider key.

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

# 6. Load the demo content (the fictional Acme Inc. knowledge base)
python3 samples/load-samples.py

# 7. Open BookStack again — you should see the chat bubble in the lower-right.
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

- **`bookstack_*` tables** — every BookStack page, kept in sync via webhooks.
- **`kb_*` tables** — uploaded documents (PDF / DOCX / Markdown / text), managed via the admin CLI.

At query time, both are searched in parallel using seven FTS5 strategies (title, exact phrase, AND, OR, proximity, chunk-level, fuzzy). Scores are fused with a multi-strategy bonus, and the top candidates are handed to the LLM as context for the final answer.

## Use Cases

**Perfect for:**

- 🏢 **Internal company wikis** — Q&A over your team's documentation
- 🎓 **Customer-facing docs portals** — "ask the docs" widget for product help
- 👋 **Employee onboarding** — new hires ask the bot before pinging a human
- 📚 **Self-hosted knowledge bases** for SMBs, agencies, research labs

**Not recommended for:**

- 🌍 **Public, unauthenticated chatbots** — the IP allow-list is the only auth layer; a public-internet deployment needs an additional auth proxy
- 🏬 **Multi-tenant SaaS** — single-tenant by design
- 📖 **Wikis larger than ~10 000 pages** — outgrow SQLite FTS5; swap in Postgres + `pgvector`
- 🧠 **Hallucination-sensitive contexts** (medical, legal advice given to end users) — the LLM still hallucinates; this is a knowledge-retrieval tool, not a source of truth

## Key Concepts

### Hybrid RAG, not pure vector search

We don't use embeddings as the primary retrieval mechanism. We run several FTS5 queries against the same index — title match, exact phrase, AND/OR keyword combinations, proximity, chunk-level, and fuzzy — and fuse the result sets with a multi-strategy bonus before handing the top candidates to the LLM. This is intentional:

- **Latency**: FTS5 returns in <10 ms over ~10k documents on a single laptop. A vector DB roundtrip is typically 50–200 ms.
- **Operational cost**: SQLite has no separate service to operate or back up.
- **Quality**: For internal docs in a single language with consistent vocabulary, BM25 / FTS5 is competitive with dense retrieval. The multi-strategy fusion compensates for queries that only one query type would find.

The `documents/knowledge_base/` layer is abstracted, so the team that needs `pgvector` later can implement it without rewriting the rest.

### Multi-provider LLM factory

The `chatbot/llm/` module exposes a single `LLMProvider` interface. The factory picks an implementation based on env vars, with this preference order:

1. Azure OpenAI (if `AZURE_OPENAI_API_KEY` is set) — most reliable for production
2. Ollama (only if `ENABLE_OLLAMA_FALLBACK=true`) — for fully-offline deployments

Switching providers is one env-var change and a container restart.

### Widget-only architecture

The chatbot has no UI of its own. There is no login, no user database, and no admin web interface. Everything user-facing happens inside the BookStack page through the embedded widget — which means **BookStack owns user identity and access control**. The chatbot trusts whatever IP / session has been allowed past BookStack and the reverse proxy.

This is deliberate: one fewer system to harden, one fewer login screen for users, and one source of truth for who can see what.

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
│   ├── llm/                      # Multi-provider LLM factory
│   ├── bookstack/                # BookStack API client + webhook handlers
│   ├── chat/                     # Widget endpoint, session, prompt building
│   ├── documents/                # RAG layer + knowledge-base management
│   ├── utils/                    # Rate limiter, DB helpers, timezone
│   ├── static/                   # CSS / JS (loaded by Flask templates)
│   └── templates/                # Jinja templates
│
├── bookstack-integration/        # Drop-in BookStack assets
│   ├── widget.html               # Paste into BookStack → Settings → Custom HTML head
│   ├── api_client.py             # Reference API client (also used in tests)
│   └── theme-functions.php       # Optional theme hook
│
├── docker/
│   ├── docker-compose.yml        # 3-service stack: bookstack, mariadb, chatbot
│   ├── mariadb-optimized.cnf     # Mariadb tuning for small instances
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
| `chatbot/llm/factory.py` | Selects and instantiates an LLM provider | Provider pattern |
| `chatbot/llm/providers/` | Azure OpenAI, Ollama implementations | `openai`, `requests` |
| `chatbot/bookstack/api_client.py` | BookStack REST client | `requests` |
| `chatbot/bookstack/webhooks.py` | Webhook endpoint for 13 BookStack events | Flask blueprint |
| `chatbot/bookstack/chunking.py` | Chunking strategy for wiki pages | Sentence-aware sliding window |
| `chatbot/documents/knowledge_base/` | KB ingestion (PDF/DOCX/MD), FTS5 indexing, hybrid search | `pypdfium2`, `pypdf`, `python-docx`, SQLite FTS5 |
| `chatbot/chat/widget_service.py` | Widget query endpoint, prompt assembly, session handling | Flask |
| `chatbot/security/` *(via utils)* | IP allow-list, sliding-window rate limit | `ipaddress`, in-memory store |
| `bookstack-integration/widget.html` | Embeddable chat bubble | Vanilla JS, ~600 LOC |
| `scripts/kb_admin.py` | Admin CLI (upload, list, delete, health) | `click`-style argparse |

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
| LLM provider | Azure OpenAI or local Ollama | Azure OpenAI (most reliable for production) |

CPU/RAM scales with corpus size — 3 GB covers wikis up to ~2 000 pages comfortably.

## Compatibility

**Fully supported:**

- Ubuntu 22.04 / 24.04 LTS, Debian 11 / 12 — x86_64 and ARM64
- Raspberry Pi 5 (8 GB) with an external SSD — for small wikis

**Should work** (untested):

- Other systemd-based distros with Docker support
- macOS for development (Docker Desktop)
- Windows 11 + WSL2

## Real-World Results

Running in production at a small business since October 2025:

- ~150 wiki pages indexed
- ~25 chat queries per business day
- Median end-to-end response time: 1.8 s (Azure OpenAI `gpt-4o-mini`)
- Zero RAG-index corruption incidents
- Cost: under €10 / month in LLM calls
- Container resource usage: ~250 MB RSS, <5 % CPU at idle

## License

MIT — see [LICENSE](LICENSE).

## Author

Marc Allgeier ([@fidpa](https://github.com/fidpa))

**Why I built this**: I needed a wiki our small team would actually use, and "great content with bad search" was killing adoption. Off-the-shelf chatbots either wanted our whole knowledge base uploaded to a third party, or pretended to be drop-in but came as a SaaS bundle. So I built the smallest thing that could work — one Flask service, one SQLite database, one widget — and ran it next to BookStack for a few months. It worked. This repo is that exact setup, with the company-specific bits stripped out.

## See Also

- [step-ca-internal-pki](https://github.com/fidpa/step-ca-internal-pki) — Internal PKI for trusted HTTPS without browser warnings
- [ubuntu-server-security](https://github.com/fidpa/ubuntu-server-security) — Security-hardening components for self-hosted servers
- [bash-production-toolkit](https://github.com/fidpa/bash-production-toolkit) — Logging, alerts, and secure-file utilities used by my other repos

## Credits

Built on top of [BookStack](https://www.bookstackapp.com/) (MIT) and [linuxserver.io's BookStack image](https://docs.linuxserver.io/images/docker-bookstack/) (GPLv3 for the container image, not the BookStack code).

---

**Production-tested since October 2025** | Flask + SQLite FTS5 + Docker | One widget, one wiki, one chatbot.
