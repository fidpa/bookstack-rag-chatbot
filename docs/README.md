# Documentation

Navigation hub for the `bookstack-rag-chatbot` docs. Files are organised loosely along the [DIATAXIS](https://diataxis.fr/) framework.

## Getting Started

| Document | What it covers |
|---|---|
| [SETUP.md](SETUP.md) | First-run installation: clone → configure → boot → ask first question |
| [CONFIGURATION.md](CONFIGURATION.md) | Every environment variable in `.env`, what it does, what to set it to |

## Reference

| Document | What it covers |
|---|---|
| [KB_ADMIN_CLI.md](KB_ADMIN_CLI.md) | Knowledge-base admin CLI: upload, list, delete, health-check |
| [BOOKSTACK_WEBHOOKS.md](BOOKSTACK_WEBHOOKS.md) | All 16 BookStack webhook events and how they map to RAG-index operations |

## Explanation

| Document | What it covers |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Why three services, why SQLite, why widget-only, what a Postgres+pgvector swap looks like |
| [RAG_DESIGN.md](RAG_DESIGN.md) | Chunking strategy, FTS5 multi-strategy retrieval, score fusion |
| [SECURITY.md](SECURITY.md) | Threat model, hardening checklist, what's deliberately out of scope |

## How-to

| Document | What it covers |
|---|---|
| [WIDGET_INTEGRATION.md](WIDGET_INTEGRATION.md) | Embedding the widget into BookStack, Wiki.js, Outline, or a custom site |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Symptom → diagnosis → fix for the most common issues |

## Recommended Reading Order

For a first-time reader who wants the full picture in 30 minutes:

1. [SETUP.md](SETUP.md) — get the stack running locally
2. [ARCHITECTURE.md](ARCHITECTURE.md) — understand the moving parts
3. [RAG_DESIGN.md](RAG_DESIGN.md) — understand what the chatbot actually does on a query
4. [WIDGET_INTEGRATION.md](WIDGET_INTEGRATION.md) — embed it where you actually want it
5. [SECURITY.md](SECURITY.md) — harden before going to production
6. [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — bookmark for later
