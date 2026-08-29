# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-08-29: Wiki pages reach the answer, and deleting one removes it from the index

### Fixed
- **Deleting a chapter or a book clears its pages from the index.** Every `chapter_*`
  event called `sync_chapter()` and every `book_*` event called `sync_book()`, so a
  delete ran the same code as a rename: the API returns nothing for an item that is
  gone, the method logged `not found`, and the pages stayed searchable. The chatbot
  could cite a page that no longer existed, which for a wiki is the case where deletion
  usually mattered. `remove_chapter_from_index()` and `remove_book_from_index()` delete
  by the `book_id` and `chapter_id` columns `sync_page()` already records, so they work
  without the API; the FTS tables follow through the existing `AFTER DELETE` triggers.
- **Wiki content reaches the model again.** `HybridSearchService` searches the
  `bookstack_*` tables and `ResultConverters` builds a virtual `KnowledgeDocument` per
  hit, but `ChunkSelectionStrategy.build_context` looked every document up in
  `kb_chunks` by `doc_id`. A wiki hit carries a string id such as `bookstack_42_page`
  and has no row there, so it contributed nothing and the assembled context held
  knowledge-base documents only. Wiki hits are now rendered from the snippet the search
  already produced.
- **A wiki page no longer takes two of the three context slots.**
  `search_bookstack_content` and `search_bookstack_chunks` find the same page under
  different synthetic ids. `build_context` now groups on the underlying BookStack item,
  and drops an excerpt a document already carries verbatim.
- **The current page reaches the context.** `ChatContextBuilder` read
  `bookstack_context["content"]` while the widget sends the field as `page_content`, so
  the branch never produced anything. The 2000-character limit is now the named constant
  `PAGE_CONTEXT_CHARS` instead of a literal inside an f-string.
- **Context ordering was inverted.** `abs()` on the FTS5 `rank` turned "lower is better"
  into "higher is better", so the weakest chunks sorted to the front and were the ones
  kept when the 3000-token budget ran out. Both sources now share one convention: FTS5
  `rank` for knowledge-base chunks, `-relevance_score` for wiki hits.
- **FTS5 `<mark>` tags no longer travel into the prompt.** `snippet()` wraps matched
  terms in them; they are stripped before the text is handed to the model.
- **The stale chunk limit in `chatbot/chat/widget_service.py`.** The comment claimed the
  widget transmits up to 3000 characters of page content;
  `getEnhancedBookStackContext()` truncates at 20000.

### Added
- **`chatbot/resync.py`, a repair path for a drifted index.** `sync_all()` existed but
  nothing called it, so an index that had fallen out of step with BookStack could not be
  rebuilt. The script ships in the container image and takes its credentials from the
  environment already there:
  `docker compose exec chatbot python resync.py --full-resync`. `--dry-run` reports what
  the index holds and writes nothing; `--no-prune` adds and updates without deleting.
- **`sync_all()` prunes what BookStack no longer reports**, which is what actually
  repairs drift, and reports honest counts: it used to promise `chapters` and `pages` in
  its statistics dict and only ever increment `books`. Pruning runs only after a walk
  that finished without errors and returned content, so an unreachable API leaves the
  index alone instead of emptying it.
- **`sync_book()`, `sync_chapter()` and `sync_page()` take an optional `seen` set**
  that collects the `(id, type)` pairs a walk touched. That set is what the prune step
  measures against; the webhook path ignores the parameter.

### Removed
- **The dead BookStack fallback in `ChatContextBuilder`.** It imported
  `BookStackSyncService` from `chatbot/bookstack/sync_service.py`, where the class is
  named `ContentSyncService`, so the import always failed and the branch never ran. It
  called a `search_content()` that does not exist, read a `content` key the real query
  returns no column for, and passed the raw user message into an FTS5 `MATCH`. The
  hybrid search covers the same ground properly, so the branch is gone rather than
  repaired.
- **`ChatContextBuilder.create_context_message()`**, dead since the widget-only rewrite.
  Nothing called it, and it carried the last German-language system prompt.

### Changed
- **The README states what the code does, along the rules of README_QUALITY_STANDARDS.**
  Four claims did not hold: `chatbot/security/` is a directory that does not exist (the
  allow-list and the rate limit live in `chatbot/utils/rate_limiter.py`), the widget was
  given as "~600 LOC" while `bookstack-integration/widget.html` counts 711 lines, the
  CPU and memory limits in `docker/docker-compose.yml` apply to the chatbot container
  only and not to all three services, and the "pluggable storage" that would let a
  Postgres backend be "dropped in" has no seam behind it: no `KnowledgeBaseService`
  interface exists anywhere in `chatbot/`, so the four knowledge-base services would
  have to be rewritten. The feature bullet is gone and the limitation is now named.
- **Three boundaries are named next to the strengths.** An empty `ALLOWED_VPN_IPS`
  admits every source and `.env.example` ships it empty; the HMAC path in
  `chatbot/bookstack/webhooks.py` is present and opt-in via `BOOKSTACK_WEBHOOK_SECRET`
  rather than absent; the 10 000-page figure is an estimate from FTS5's behaviour, while
  the deployment the numbers come from indexes about 150 pages. Provider selection now
  says that Azure needs `AZURE_OPENAI_ENDPOINT` as well as the API key, and the two
  German `ValueError` strings in `chatbot/llm/factory.py` are declared.
- **`docs/ARCHITECTURE.md` and `docs/RAG_DESIGN.md` no longer promise an interface that
  is not there.** Both described the Postgres move as implementing a
  `KnowledgeBaseService`; the name appears nowhere in `chatbot/`. Both now say what the
  move costs, namely rewriting `StorageService`, `IndexingService`, `SearchService` and
  `ContextService`, with extracting the interface as step zero, and the row in "Where to
  Modify What" says the same. The `LLMProvider` block in `docs/ARCHITECTURE.md` now
  carries the signatures of `chatbot/llm/base.py` rather than a tidied-up version of
  them, and the ~10k-document latency column is labelled as the estimate it is.
- **The ten documents under `docs/` describe the code that is there.** The pass found
  invented interfaces in four of them. `docs/KB_ADMIN_CLI.md` documented a CLI that does
  not exist: subcommand `document` instead of `documents`, positional file arguments
  instead of `--file`, `--collection`, `--force` and `--verbose` flags that were never
  defined, a `debug search` command, `--format ids`, and UUID document IDs where
  `--id` is `type=int`. It is rewritten from the actual `--help` of all five subcommand
  groups, and now states that `scripts/` is not in the container image (the build
  context is `../chatbot`), so the documented
  `docker compose exec chatbot python3 /app/scripts/kb_admin.py` could not have run, and
  that `PYTHONPATH=chatbot` is required on the host.
- **`docs/WIDGET_INTEGRATION.md` no longer documents a configuration surface.** The
  `window.KnowledgeBotChat.config` object, the keys `position`, `accent`, `startMessage`,
  `apiBase`, `placeholder` and `closeLabel`, the `--kb-*` CSS variables and the
  `data-knowledgebot-disabled` attribute are all absent from
  `bookstack-integration/widget.html`, which assigns `window.KnowledgeBotChat` at load
  and would overwrite any pre-set config anyway. The page now says where each literal
  sits, describes how `getApiUrl()` derives the endpoint from `window.location`, and
  drops the "embed elsewhere" recipe that loaded the file through `innerHTML`, which
  does not execute script elements.
- **`docs/SECURITY.md` claimed three prompt-injection mitigations that do not exist.**
  There are no delimiters around the retrieved context, no instruction to treat it as
  data, and no check that an answer cites a source; `widget_service.py` interpolates
  `combined_context` into a system message verbatim. The section now says so and names
  what would raise the bar. Added in the same pass: `SECRET_KEY` falls back to a literal
  published in this repository rather than failing startup, `/webhook/bookstack/test`
  answers unauthenticated, prompts and messages are logged at `INFO`, and the widget's
  `textContent` assignment is the real XSS defence that had gone unmentioned. Anthropic
  is gone from the provider list; the code dropped it.
- **`docs/BOOKSTACK_WEBHOOKS.md` describes the three handler branches, not thirteen.**
  The per-event action column claimed behaviour the code does not have: every
  `chapter_*` event calls `sync_chapter()` and every `book_*` event calls `sync_book()`,
  so `chapter_delete` and `book_delete` remove nothing from the index. The full-resync
  recipe invoked `python -m chatbot.bookstack.sync_service --full-resync`, which has no
  `__main__` block and no CLI; `sync_all()` exists and nothing calls it. The manual test
  payload used `related_item` where the handler reads `related.<type>.id`.
- **`docs/RAG_DESIGN.md` prompt-assembly section is replaced by the real prompt.** The
  documented `<SOURCES>` block with numbered source URIs does not exist; the context is
  built by `ChunkSelectionStrategy.build_context` with German section labels, three
  documents at three chunks and 3000 tokens, and no URLs at all. The page also records
  that four of the seven strategies are conditional, that the two BookStack searches
  share the `KEYWORD_OR` and `CHUNK_BASED` buckets, that `kb_chunks_fts` indexes one
  column rather than three, and and how wiki content actually reaches the
  context now that the retrieval bugs listed under Fixed are repaired.
- **`docs/CONFIGURATION.md` covers the variables it claimed to cover.**
  `CHATBOT_SYSTEM_PROMPT`, `DATABASE_PATH` and `BOOKSTACK_API_URL` were missing;
  `SECRET_KEY` was listed as required when it has a fallback; `ALLOWED_VPN_IPS` did not
  say that a non-empty list with no parseable CIDR denies everything; the upload limits
  and accepted extensions were absent; and the `#why-sqlite` anchor did not resolve
  against its heading.
- **`docs/SETUP.md` and `docs/TROUBLESHOOTING.md` give commands that run.** The demo
  loader needs `requests`; the reindex example named `document reindex --all` for what
  is `bulk reindex --force`; the memory knob is `deploy.resources.limits.memory`, not
  `mem_limit`; there is no `widget.js` to 404 on and no `search` subcommand; and the
  claim that the chatbot "fails fast on a missing env var" is the opposite of what
  `config.py` does.
- **Typography across `docs/`.** 54 em dashes and three en dashes replaced without `--`
  inserts, box-drawing diagrams untouched.
- **Quick Start step 6 runs as written.** `samples/load-samples.py` reads its BookStack
  credentials from the environment and imports `requests`; the step now installs the
  dependency and sources `.env` before calling the loader.
- **Typography and prose follow the release-message rules.** The 36 em dashes and the
  one en dash are replaced without `--` inserts, the box-drawing diagram stays. The
  `**The Problem**:` template, the doubled production-tested claim and the three
  repetitions of the pgvector sentence are gone.

### Upgrade notes

No reindex is required: chunking, the FTS5 schema and the environment variables are
unchanged, and the retrieval fixes take effect on the existing index.

One repair is worth running once. Chapters and books deleted under v0.1.4 or earlier
left their pages in the index, and nothing removed them retroactively. Until you clear
them, the chatbot can still cite a page that no longer exists:

    docker compose -f docker/docker-compose.yml exec chatbot python resync.py --dry-run
    docker compose -f docker/docker-compose.yml exec chatbot python resync.py --full-resync

The second command rebuilds the index from the BookStack API and drops what BookStack
no longer reports. It writes to the same SQLite file as the running app, so pick a quiet
moment.

## [0.1.4] - 2026-08-28: Bookshelf webhooks no longer report work they never did

Three of the sixteen events the webhook endpoint accepted had no branch behind them.
`bookstack_webhook()` in `chatbot/bookstack/webhooks.py` branches on page, chapter and
book, and reads a shelf nowhere; because `bookshelf_*` starts with the same letters as
`book_*`, `bookshelf_create`, `bookshelf_update` and `bookshelf_delete` reached the book
branch, which looks for `related.book.id`. A shelf change therefore left the index
untouched while the endpoint answered `{"status": "processed"}` and the documentation
recorded an index operation for each of the three.

### Fixed
- **A bookshelf change is now answered with `ignored` instead of `processed`.** The three
  `bookshelf_*` events are gone from `RELEVANT_EVENTS` in
  `chatbot/bookstack/webhooks.py`, so the endpoint states what it does rather than
  claiming a synchronisation it never ran. Thirteen events remain, each with a branch that
  reaches `ContentSyncService`.
- **Browsers stop requesting assets under a version that no longer exists.** The
  `APP_VERSION` fallback in `chatbot/app.py` had stayed at `0.1.1` while `CLI_VERSION` in
  `scripts/kb_admin.py` and the README badge moved on with v0.1.2. Nothing sets
  `APP_VERSION`, so the fallback is the value that ships. All three now read `0.1.4`.
- **The webhook documentation describes what the code does.** `docs/BOOKSTACK_WEBHOOKS.md`
  listed sixteen events and gave each `bookshelf_*` entry an index action;
  `README.md`, `docs/README.md` and `docs/ARCHITECTURE.md` repeated the count in six more
  places. All of them now say thirteen, and the webhook page says why the shelf events are
  absent.

### Upgrade notes

If a BookStack webhook is subscribed to the three `bookshelf_*` events, it can be
unsubscribed. Nothing changes if it stays subscribed: those deliveries never altered the
index, and they are now answered with `ignored` instead of `processed`. No re-index is
needed, and no other event changes behaviour.

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
