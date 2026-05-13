# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.2] — 2026-05-13

### Fixed
- Black formatting applied across all Python files (69 files reformatted)

## [0.1.1] — 2026-05-13

### Fixed
- Ruff lint errors: bare `except` clauses, unused imports, unused variables, single-line class definitions, f-strings without placeholders

## [0.1.0] — 2026-05-13

### Added
- Initial public release, extracted from internal production deployment (running since October 2025)
- Flask-based RAG chatbot backend (`chatbot/`) with multi-provider LLM factory (Azure OpenAI, Ollama)
- Hybrid RAG: SQLite FTS5 full-text search across BookStack content **and** an independent knowledge base
- Embedded JavaScript chat widget for BookStack pages (`bookstack-integration/widget.html`)
- 16 BookStack webhook event handlers for real-time content synchronisation
- IP-based access control + sliding-window rate limiting
- Admin CLI for knowledge-base management (`scripts/kb_admin.py`)
- Docker Compose stack (BookStack + MariaDB + chatbot backend) with security hardening (`no-new-privileges`, resource limits, healthchecks)
- Synthetic sample document set for the fictional `Acme Inc.` company, plus `samples/load-samples.py` loader
- DIATAXIS-style documentation in `docs/`
- GitHub Actions: lint workflow (ruff, black, mypy, yamllint, shellcheck) and release workflow

### Security
- All credentials externalised via `.env` (template in `.env.example`)
- Containers run with `no-new-privileges:true` and explicit CPU/RAM limits
- Default Ollama fallback disabled to prevent unintended local-model usage
