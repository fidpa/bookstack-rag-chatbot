# Contributing

Thanks for your interest in improving `bookstack-rag-chatbot`. This project welcomes pull requests, issue reports, and discussion.

## Ground Rules

- Be respectful — see [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
- Open an issue **before** large changes so we can agree on scope.
- Keep PRs focused. One topic per PR.

## Development Setup

```bash
git clone https://github.com/fidpa/bookstack-rag-chatbot.git
cd bookstack-rag-chatbot

# Python tooling
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r chatbot/requirements.txt   # includes pytest
pip install ruff black mypy

# Docker stack (BookStack + chatbot backend + MariaDB)
cp .env.example .env
# Edit .env: set at minimum BOOKSTACK_DB_PASSWORD, MYSQL_ROOT_PASSWORD, SECRET_KEY,
# and one LLM provider (AZURE_OPENAI_API_KEY or ENABLE_OLLAMA_FALLBACK=true)
docker compose -f docker/docker-compose.yml up -d
```

## Code Style

| Layer | Tooling | Command |
|---|---|---|
| Python | `ruff` + `black` | `ruff check chatbot scripts tests samples && black --check chatbot scripts tests samples` |
| Python types | `mypy` | `mypy --ignore-missing-imports chatbot` |
| YAML | `yamllint` | `yamllint -d relaxed .` |

These are the checks `.github/workflows/lint.yml` runs, and all of them gate the build.
Run them before pushing:

```bash
ruff check chatbot scripts tests samples && black --check chatbot scripts tests samples \
  && mypy --ignore-missing-imports chatbot && pytest -q
```

New code, comments and log messages are English. Some older modules under
`chatbot/documents/knowledge_base/` still carry German; the German stopword and intent
lists in `query_processor/constants.py` are language data and stay.

## Tests

```bash
pytest -q
```

The suite needs no BookStack, LLM or Docker: `tests/conftest.py` points `DATABASE_PATH`
at a temporary file and provides a fake BookStack API. CI runs it on every push. Tests
marked `integration` talk to a real BookStack and skip themselves unless
`BOOKSTACK_TOKEN_ID` is set; see [tests/README.md](tests/README.md).

New behaviour ships with a test, and a fixed bug with a test that fails without the fix.

## Commit Messages

Conventional Commits format:

```
<type>: <short description>

<optional body>
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `ci`.

## Pull Request Checklist

- [ ] Lint suite passes (`ruff`, `black`, `mypy`)
- [ ] Tests pass and new behaviour is covered
- [ ] Documentation in `docs/` updated where relevant
- [ ] `CHANGELOG.md` entry added under `## [Unreleased]`
- [ ] No secrets, internal IPs, or personal paths in the diff

## Areas Where Help Is Welcome

- Additional LLM providers (Mistral, Groq, local llama.cpp servers)
- Postgres + `pgvector` backend (alternative to SQLite FTS5 for larger corpora)
- Integration adapters for other wikis (Wiki.js, Outline, Bookshelf)
- Improved chunking strategies (semantic chunking, hierarchical RAG)
- Internationalisation of the widget UI

## Reporting Security Issues

Please **do not** open public issues for security vulnerabilities. See [SECURITY.md](SECURITY.md) for the responsible disclosure process.
