# Documentation

Navigation hub for the `bookstack-rag-chatbot` docs. Files are organised loosely along the [DIATAXIS](https://diataxis.fr/) framework.

## Getting Started

| Document | What it covers |
|---|---|
| [SETUP.md](SETUP.md) | First-run installation: clone, configure, boot, ask the first question |
| [CONFIGURATION.md](CONFIGURATION.md) | Every environment variable the chatbot reads, its real default, and which quiet defaults to override |

## Reference

| Document | What it covers |
|---|---|
| [KB_ADMIN_CLI.md](KB_ADMIN_CLI.md) | Knowledge-base admin CLI: the five subcommand groups quoted from `--help`, and how to run it on the host |
| [BOOKSTACK_WEBHOOKS.md](BOOKSTACK_WEBHOOKS.md) | The 13 BookStack webhook events, which of the three handler branches each takes, and what deletion does not do |

## Explanation

| Document | What it covers |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Why three services, why SQLite, why widget-only, and what a Postgres+pgvector move would actually cost |
| [RAG_DESIGN.md](RAG_DESIGN.md) | Chunking, the seven FTS5 strategies and when each fires, score fusion, and what the prompt really contains |
| [SECURITY.md](SECURITY.md) | What guards the endpoints, what prompt injection is not defended against, hardening checklist |

## How-to

| Document | What it covers |
|---|---|
| [WIDGET_INTEGRATION.md](WIDGET_INTEGRATION.md) | Embedding the widget, where it sends its requests, and which literals to edit to change it |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Symptom, diagnosis and fix for the most common issues |

## Recommended Reading Order

For a first-time reader who wants the full picture in 30 minutes:

1. [SETUP.md](SETUP.md): get the stack running locally
2. [ARCHITECTURE.md](ARCHITECTURE.md): understand the moving parts
3. [RAG_DESIGN.md](RAG_DESIGN.md): what the chatbot does on a query
4. [WIDGET_INTEGRATION.md](WIDGET_INTEGRATION.md): embed it where you want it
5. [SECURITY.md](SECURITY.md): harden before going to production
6. [TROUBLESHOOTING.md](TROUBLESHOOTING.md): bookmark for later
