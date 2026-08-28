# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.3] - 2026-08-28: Release pages are built from this file, and the lint gate is pinned

The three releases of 13 May 2026 were published by hand. `.github/workflows/release.yml`
had been pushed while GitHub Actions was switched off for the repository, so GitHub never
registered it: `actions/workflows` and `actions/runs` both report `total_count: 0`. Their
titles therefore carried nothing but the tag name, and their bodies were typed alongside
this file instead of being cut from it. This release makes this file the source of both,
and pins the lint rule set before the workflow runs for the first time: with an unpinned
Ruff the unchanged tree reports 653 findings, with the rule set the repository was linted
against it is clean.

The older sections were checked against the tags they describe and corrected where the
code contradicted them; the corrections are listed below. Every measured value, path and
identifier that held up is unchanged.

### Added
- **`ruff.toml` pins the lint gate to the rule set the repository was written against.**
  `lint.yml` installs Ruff unpinned, so a new default rule set moves the gate without a
  commit: Ruff 0.16 reports 653 findings on the same tree that passes under `E4`, `E7`,
  `E9` and `F`. The file fixes that selection.

### Changed
- **Release titles and bodies now come from this file.** `.github/workflows/release.yml`
  cuts the section belonging to the pushed tag out of `CHANGELOG.md`, strips leading blank
  lines, and reads the headline behind the date of the section heading into the release
  name. From this release on, section headings carry that headline
  (`## [X.Y.Z] - YYYY-MM-DD: <headline>`). Where a heading has none, the workflow logs a
  warning and falls back to the plain tag name.
- **Every entry opens with what the release changes for an operator**, with the cause in
  the paragraph below it and a file, function or configuration variable to check it
  against. The feature list of the first release keeps its list form.
- **This file is plain ASCII.** The em dashes in the three section headings are now
  hyphens.
- **Local agent tooling can no longer be staged by accident.** `.gitignore` did not cover
  `.claude/`, so the directory showed up as untracked in every `git status`; it is ignored
  now, together with `CLAUDE.md`, `TODO.md`, `NOTES.md` and `*_TEMPLATE.md`. Nothing of
  that kind was ever committed.

### Fixed
- **The v0.1.2 formatting pass covered the three directories the CI lints, not the whole
  tree.** `lint.yml` runs `black` over `chatbot`, `scripts` and `tests`, which is 69 of the
  71 Python files in the tree; `bookstack-integration/api_client.py` and
  `samples/load-samples.py` sit outside those paths and were never reformatted. The
  `[0.1.2]` entry said "all Python files".
- **The webhook endpoint accepts sixteen BookStack events and synchronises thirteen of
  them.** `RELEVANT_EVENTS` in `chatbot/bookstack/webhooks.py` lists sixteen, and the
  endpoint branches on page, chapter and book events; the three `bookshelf_*` events reach
  no synchronisation path. The `[0.1.0]` entry called all sixteen of them handlers.
- **Resource limits apply to the `chatbot` service, not to every container.**
  `docker/docker-compose.yml` sets `no-new-privileges:true` and a healthcheck on all three
  services, but `deploy.resources` only on `chatbot`. The `[0.1.0]` entries put both under
  "containers".
- **The published v0.1.0 body described an embedding step the documentation does not
  describe.** It said the widget goes in through a single `<script>` tag;
  `docs/WIDGET_INTEGRATION.md` describes pasting the whole of
  `bookstack-integration/widget.html`, style block and markup included, into BookStack's
  custom head field. The section in this file said it correctly, and the body is now that
  section.

## [0.1.2] - 2026-05-13: Black formatting across the linted paths

### Changed
- **`black --check chatbot scripts tests` passes.** The run reformatted all 69 Python
  files under those three paths. The two Python files outside them,
  `bookstack-integration/api_client.py` and `samples/load-samples.py`, are unchanged;
  `lint.yml` does not lint them.
- **The admin CLI reports `0.1.2`.** `CLI_VERSION` in `scripts/kb_admin.py` and the
  version badge in `README.md` follow the tag. The `APP_VERSION` fallback in
  `chatbot/app.py` was not raised with them and still reads `0.1.1`.

## [0.1.1] - 2026-05-13: Ruff findings cleared across the linted paths

### Fixed
- **`ruff check chatbot scripts tests` passes.** The run replaced bare `except` clauses
  with `except Exception`, removed unused imports and unused variables, split the
  single-line dummy exception classes in `chatbot/llm/providers/azure.py`, dropped the `f`
  prefix from strings without placeholders, and turned one `not ... in` into `not in`
  (`chatbot/bookstack/chunking.py`). The star imports that have to stay carry a `# noqa`
  with their rule code (`chatbot/chat/routes/__init__.py`).
- **The version reads `0.1.1` in all three places that carry it.** `CLI_VERSION` in
  `scripts/kb_admin.py`, the `APP_VERSION` fallback in `chatbot/app.py` and the version
  badge in `README.md`.

## [0.1.0] - 2026-05-13: First public release of the BookStack RAG chatbot

Extracted from an internal production deployment that had been running since October 2025.
The company-specific parts were removed and the stack comes up against the synthetic
`Acme Inc.` demo wiki that ships with it. One trace of the original domain is still in the
code: `preprocess_for_fts5()` in
`chatbot/documents/knowledge_base/services/query_processor/preprocessor.py` runs its
ICD-code and medical-synonym boost by default.

### Added
- **Wiki questions are answered from the wiki's own content.** A Flask backend
  (`chatbot/`) retrieves over two SQLite FTS5 index sets, the BookStack mirror created in
  `chatbot/bookstack/sync_service.py` and the uploaded-document index created in
  `scripts/init_kb_schema.py`, and hands what it finds to the LLM as context.
- **The LLM provider is an environment variable, not a code change.**
  `create_llm_provider()` in `chatbot/llm/factory.py` serves Azure OpenAI and Ollama behind
  one interface.
- **The chat reaches readers without forking BookStack.**
  `bookstack-integration/widget.html` goes into BookStack's custom head content field and
  puts a chat bubble on every wiki page; `docs/WIDGET_INTEGRATION.md` walks through it.
- **The index follows the wiki without a cron job.** `chatbot/bookstack/webhooks.py`
  accepts sixteen BookStack events and re-indexes on page, chapter and book events;
  setting `BOOKSTACK_WEBHOOK_SECRET` turns on the HMAC-SHA256 check of the payload.
- **Requests are filtered before they reach the LLM.** `chatbot/utils/rate_limiter.py`
  enforces the `ALLOWED_VPN_IPS` allow-list and a sliding-window cap per source IP
  (`RATE_LIMIT_PER_MINUTE`, default 30).
- **The knowledge base is managed from the command line.** `scripts/kb_admin.py` groups
  its subcommands into `documents`, `bulk`, `index`, `stats` and `maintenance`;
  `scripts/init_kb_schema.py` creates the schema it works on.
- **The whole stack comes up from one compose file.** `docker/docker-compose.yml` runs
  BookStack, MariaDB and the chatbot backend, each with a healthcheck.
- **A first run needs no real wiki.** `samples/` carries five documents for the fictional
  `Acme Inc.` company plus the `samples/load-samples.py` loader.
- **The documentation is split by task.** Ten files in `docs/` cover setup, architecture,
  RAG design, widget integration, webhooks, security, the admin CLI, configuration and
  troubleshooting.
- **Linting and releasing are wired up.** `.github/workflows/lint.yml` runs ruff, black and
  mypy over `chatbot`, `scripts` and `tests`, shellcheck over `scripts` and yamllint over
  the tree; `.github/workflows/release.yml` publishes a release when a tag is pushed.

### Security
- **Credentials live outside the repository.** They come from `.env`, and `.env.example`
  documents the full set. `SECRET_KEY` carries a fallback in `chatbot/config.py`, and it
  is a placeholder that says so in its own value.
- **Containers cannot gain privileges.** `no-new-privileges:true` is set on all three
  services in `docker/docker-compose.yml`; the `chatbot` service additionally carries CPU
  and memory limits.
- **The local model stays off until it is switched on.** `ENABLE_OLLAMA_FALLBACK` defaults
  to `false`, so with no Azure credentials `create_llm_provider()` raises instead of
  falling through to whatever Ollama happens to serve.
