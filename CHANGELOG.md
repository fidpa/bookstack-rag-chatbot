# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.1] - 2026-10-01: Upgrades rebuild the chatbot, and webhook syncs survive a BookStack restart

### Fixed
- **Upgrading needs a rebuild of the chatbot image, and the 0.4.0 upgrade notes did not
  say so.** The chatbot is built from the repository (`build:` in `docker-compose.yml`),
  and `docker compose up -d` builds an image only when none exists. A stack upgraded from
  v0.3.0 as the 0.4.0 notes described got the new BookStack and MariaDB images but kept
  running the v0.3.0 chatbot (`/health` answered `"version": "0.3.0"`), without any of the
  webhook fixes; the newly subscribed `recycle_bin_restore` was ignored. Upgrade with
  `up -d --build` (see Upgrade notes); the compose file's header says so now.
- **A webhook sync is retried while BookStack does not answer.** Since 0.4.0 only create
  events were retried. A `page_update` read back while BookStack was restarting got
  `Connection refused`, was given up on after one attempt, and the edit stayed out of the
  index until a full resync (seen against BookStack 25.07.3). Every event is now retried
  after 3, 6 and 12 s while BookStack refuses the connection, times out, or answers `429`
  or `5xx`, also when a book or chapter loads but one of its pages does not; an item that
  BookStack answers with `404` (or `401`) is still given up on at once, except after a
  create event. A request that hangs until the 30-second timeout makes each attempt that
  long, so the queue waits correspondingly. The `gave up` warning no longer says the item
  was deleted or restricted when the cause may be a refused token or a failed write.
- **A retried job no longer brings back an old page URL.** A job retried while BookStack
  was down could run after a newer event for the same page and store the URL from its
  own, older payload (before a move or rename). Each page job now uses the URL of the
  latest page event for that page. A book rename or a chapter move to another book sends
  no page event, so a page job retried after one of those can still store the old URL.
- **An answer that is not JSON is not retried.** A wrong `BOOKSTACK_API_URL` or a login
  page answers `200` with HTML; that counted as "BookStack does not answer". It is now
  reported as such and given up on.
- **Restoring after `down -v`.** `docs/TROUBLESHOOTING.md` ended its last-resort recipe
  with "re-run setup, then restore DB". It now gives the restore command (run against
  BookStack 25.07.3: users, roles, tokens, webhooks, the custom head and all content came
  back) and the resync after it, and says that `down -v` also deletes the `chatbot_data`
  volume with the documents uploaded through `kb_admin.py`.
- **Setup steps that BookStack 25.07 refuses.** *Add New User* sends an invite email by
  default and, without mail settings, refuses to save the user; the webhook form requires a
  request timeout. `docs/SETUP.md` and `docs/BOOKSTACK_WEBHOOKS.md` now say to clear the
  invite and set a password, and to enter a timeout. `pip install requests` is refused on
  Debian 12 and Ubuntu 24.04 (externally managed Python); the quickstart names the apt
  package.
- **Documentation corrections.** BookStack also sends `book_create` and `chapter_move` from
  inside its transaction (`BookRepo::create`, `ChapterRepo::move`); `book_create` was
  already retried and now has a test. The quickstart no longer calls a token for the admin
  merely second best. `docs/TROUBLESHOOTING.md` explains BookStack's API rate limit (180
  requests per minute by default, `API_REQUESTS_PER_MIN`), which a large book or a full
  resync of a larger wiki runs into.

### Changed
- **`BookStackClient.get_book()`, `get_chapter()` and `get_page()` raise
  `BookStackAPIError` when BookStack does not answer** (no response, `429`, `5xx`); they
  return `None` only when BookStack refuses the item or answers without JSON. The
  exception carries `status` and `transient`. Inside this repository only the sync service
  calls them, and it handles both; code of your own that calls them should catch the
  exception.

### Upgrade notes
No schema change, no new variable. The chatbot image is built from the repository, so
every upgrade that changes its code needs `--build`; `up -d` alone keeps the old image.

- **From v0.4.0:** update the code, then

      docker compose --env-file .env -f docker/docker-compose.yml up -d --build

- **From v0.3.0:** work through the 0.4.0 upgrade notes first, with one change: where
  they lead to `up -d`, run the command above instead. Their steps 1 (compare the
  configuration) and 4 (set `CHATBOT_BIND` if clients reached port 8888 directly) belong
  before it.
- **Upgraded to 0.4.0 without `--build`:** BookStack and MariaDB run the new tags, the
  port binding of 0.4.0 is already in effect (it comes from the compose file), but the
  chatbot is still v0.3.0. Run the command above, then the full resync from step 6 of the
  0.4.0 notes.

In every case, check that `curl -s localhost:8888/health` reports the new version.

## [0.4.0] - 2026-10-01: New pages and moves reach the index, and the quickstart runs as written

### Fixed
- **New pages and chapters, moves and sorts reach the index.** BookStack sends
  `page_create`, `chapter_create`, `page_move` and `book_sort` from inside the database
  transaction that makes the change, and the handler read the item back inside the
  request: it saw a new page as a draft, a new chapter as 404 and a moved page in its old
  chapter. New content only reached the index with a later edit or a full resync. The
  endpoint now answers at once, and a background worker
  (`chatbot/bookstack/webhook_worker.py`) reads BookStack two seconds later, one job after
  the other; a new item that is not visible yet is tried again after 3, 6 and 12 s.
  Checked against BookStack 25.07.3: pages and chapters created through the API or the
  editor were in the index after about 3 s, moves and sorts made in the UI after 3 to 5 s.
- **Restoring from the recycle bin reaches the index.** A restore sends
  `recycle_bin_restore`, not `page_restore`, and its payload names no item, so restored
  content stayed out of the index until a full resync. The event is now handled: five
  seconds later the whole wiki is walked without pruning (a restored page was back after
  about 9 s against BookStack 25.07.3). The walk is repeated only if no book could be
  read at all.
- **A second book sort no longer works from stale data.** The API client cached books,
  chapters and pages for five minutes. A `book_sort` within that window re-indexed a page
  in the chapter it had just left, and a following `chapter_delete` removed the page from
  the index. The cache is gone; every sync reads BookStack as it is.
- **A full resync no longer reports success when BookStack cannot be reached.**
  `get_all_books()` turned an API error into an empty list, so a wrong URL or a refused
  token printed `errors: 0` and exited 0. It now raises, `sync_all()` counts the error and
  skips the prune, and `resync.py` exits 1 with a hint.
- **`/health` reports a failed database setup.** When the startup migration could not
  write the database (a root-owned volume after an upgrade, for instance), the app logged
  the error and `/health` still answered `healthy`. It now answers 503 `unhealthy`, and
  the container shows as unhealthy (after 65 s with the shipped health check).
- **The quickstart runs as written.** The image tags `lscr.io/linuxserver/bookstack:25.07`
  and `lscr.io/linuxserver/mariadb:11.5` never existed, so `docker compose up` failed at
  the first pull for every new installation. The tags are now `25.07.3` and `11.4.9`, and
  a new CI job (`images` in `lint.yml`) runs `docker manifest inspect` on every tag in the
  compose file. The documented `APP_KEY` command started the image's init system and hung;
  it is now `docker run --rm --entrypoint /bin/bash lscr.io/linuxserver/bookstack:25.07.3
  appkey`. Compose reads `.env` from `docker/`, not from the repository root, so every
  variable stayed empty, `ALLOWED_VPN_IPS` included, and empty allows every source; every
  documented command now passes `--env-file .env`. `docker compose restart` keeps the old
  environment, so new tokens were never picked up; the docs now use `up -d`.
- **The sample loader works next to a read-only chatbot token.** `samples/load-samples.py`
  creates a book and pages with `BOOKSTACK_TOKEN_*`, which the docs now recommend to be
  read-only, and BookStack answered 403. It now takes `SAMPLES_TOKEN_ID` and
  `SAMPLES_TOKEN_SECRET` when set and explains a refusal.
- **The backup before `down -v` saves the wiki.** The command in `docs/TROUBLESHOOTING.md`
  (`mysqldump -u root -p"$MYSQL_ROOT_PASSWORD"`) wrote an empty file: the host shell
  expands the variable, and the MariaDB image refuses root with a password from inside
  the container. It now runs `mariadb-dump` as the application user and checks the dump
  before anything is deleted.
- **The MariaDB health check signs in.** It used root with `MYSQL_ROOT_PASSWORD`, which
  was refused on every check and logged a warning every 30 s; it only passed because
  `ping` reports a running server even when the sign-in fails. It now uses `mariadb-admin`
  with the application user.
- **The widgets say why a question was refused.** A 400 from the API showed as
  "Connection error: HTTP error! status: 400". Both widgets now show the API's message,
  and their input stops at 2,000 characters.
- **Documentation corrections.** The API token is created under My Account > Access &
  Security > API Tokens, or for another user under Settings > Users. BookStack's default
  sign-in is `admin@admin.com` / `password`, not credentials printed at first boot. The
  seven search strategies run over uploaded documents; wiki content is searched by
  keyword (OR) at page and chunk level. A chunk can exceed the target size (up to about
  1.2 times with the defaults, measured on random texts). `resync.py --dry-run` creates
  the database schema if it is missing. The widget does not special-case `[::1]`.
  "Before v0.1.5" meant v0.2.0. After fixing a root-owned volume, the chatbot needs a
  `restart`, because `up -d` leaves an unchanged running container alone.

### Security
- **Questions are limited to 2,000 characters, and keyword extraction is linear.**
  `QueryAnalyzer.extract_keywords()` checked for duplicates against a list, so its cost
  grew with the square of the question: 40,000 distinct words took 7.6 s (measured on
  v0.3.0), and a client past the allow-list could send up to the 16 MB request limit. The
  widget API now answers 400 above 2,000 characters, cuts the page title at 300 and the
  URL at 2,000 characters and drops context fields that are not text; 60,000 distinct
  words are analysed in 0.2 s (test suite).
- **The chatbot port is published on loopback by default.** `docker-compose.yml`
  published port 8888 on all interfaces. Behind a proxy with `TRUSTED_PROXY_HOPS=1`, a
  client that reached the port directly could set `X-Forwarded-For` itself and pass the
  allow-list. The new `CHATBOT_BIND` defaults to `127.0.0.1`.
- **BookStack permissions are documented as they work.** The README said BookStack owns
  access control; in fact the chatbot indexes what the API token's user can see and
  answers every client that passes the allow-list from that index. README, `SECURITY.md`,
  `docs/SECURITY.md` and `docs/SETUP.md` now say so and set up a dedicated view-only user
  for the token. A page restricted later leaves the index with the next full resync;
  BookStack's `permissions_update` event is not handled yet.

### Added
- **`CHATBOT_BIND`**, the host address the chatbot port is published on (default
  `127.0.0.1`), and **`SAMPLES_TOKEN_ID` / `SAMPLES_TOKEN_SECRET`** for the sample loader.
  Both are in `.env.example` and `docs/CONFIGURATION.md`.
- **Tests for every fix above.** The suite grew from 63 to 148 tests (plus the 2 live
  tests), among them the real `BookStackClient` over a stand-in transport, the webhook
  worker, `resync.py`, the Azure provider against a mocked transport, the compose file,
  and both widget scripts run in node (skipped where node is missing).

### Changed
- **Webhook responses.** Deletions are applied at once and answered `200 processed`; the
  same removal is queued once more, so a sync that read the item just before BookStack
  deleted it cannot write it back. Every other event is answered `202 queued`. A failed
  sync shows as `Webhook job ... gave up` in the chatbot log, not in BookStack. At most
  500 jobs wait; beyond that the event is answered 503, and BookStack does not retry it.
  Only create events are retried; an existing item that cannot be read is deleted or
  hidden from the token's user.
- **"Real-World Results" in the README is now "Reported Figures".** The numbers come from
  the deployment this repository was extracted from and were not re-measured against this
  code; the claim that no index rebuild had been needed is gone.

### Upgrade notes
No schema change and no reindex. For a running stack:

1. Run every Compose command from the repository root with `--env-file .env`. Compose
   never read the `.env` in the repository root, so a stack started as documented before
   ran with empty variables. If you supplied the values another way (`docker/.env`,
   exported variables), compare
   `docker compose --env-file .env -f docker/docker-compose.yml config` with your running
   setup before `up -d`.
2. New image tags: `lscr.io/linuxserver/bookstack:25.07.3` and
   `lscr.io/linuxserver/mariadb:11.4.9`. The previous tags never existed, so your
   `mariadb_data` volume was created by the tag you chose yourself. Check it first with
   `docker exec bookstack_db mariadb --version`: from 11.4.x the update to 11.4.9 was
   tested on an existing volume; if you run a newer MariaDB, keep your tag rather than
   going back.
3. If the `chatbot_data` volume was created by an image before v0.3.0 and is root-owned,
   fix it before the first `up -d`:

       docker compose --env-file .env -f docker/docker-compose.yml run --rm --user root chatbot chown -R 1000:1000 /app/data

4. The chatbot port is now published on `127.0.0.1` only. If clients reached port 8888
   directly on the server's address, set `CHATBOT_BIND=0.0.0.0` (IPv4 only) and fill in
   `ALLOWED_VPN_IPS` first.
5. In BookStack's webhook, additionally subscribe `recycle_bin_restore`.
6. Recreate the API token for a dedicated BookStack user whose role sees only what
   everyone with chatbot access may read (`docs/SETUP.md`, step 5), then run a full resync
   once so that restricted pages already in the index are dropped:

       docker compose --env-file .env -f docker/docker-compose.yml exec chatbot python resync.py --full-resync

## [0.3.0] - 2026-09-28: Webhooks, full resyncs and chunk search work, and the index no longer corrupts itself

### Fixed
- **BookStack webhooks update the index.** The handler read the item id from
  `related.<type>.id`; BookStack's `WebhookFormatter` sends it as `related_item.id`. Every
  real delivery was answered `processed` and changed nothing, so the index only moved
  when someone ran a full resync. v0.2.0 adjusted the documented test payload to the
  handler instead of the other way round; both now use `related_item`. A payload without
  the id is answered with 400 instead of `processed`.
- **A full resync indexes pages and chapters.** `sync_book()` read `book["chapters"]` and
  `book["pages"]`; BookStack's book endpoint lists both under `contents`. The walk stored
  the book rows only, and the prune step then deleted every page and chapter, which is
  what the v0.2.0 upgrade notes told operators to run. The book list is now paged through
  in batches of 500 instead of stopping at BookStack's default page of 100.
- **Wiki chunks are stored.** `_store_content()` kept its write transaction open and
  `_store_content_chunks()` wrote on a second connection, which waited for the lock, gave
  up after SQLite's 5 s timeout and had its error swallowed. `bookstack_chunks` stayed
  empty in every installation and each synced item cost 5 s (measured on a scratch
  database: 5.0 s per item, 0 chunk rows). Content and chunks are now written in one
  transaction.
- **The full-text indexes no longer corrupt on update or delete.** All three FTS5 tables
  use external content, and their triggers removed old rows with plain `DELETE` and
  `UPDATE` statements, which read the terms to remove from the content table after the
  change. Old terms stayed in the index; a query for a word only the previous version of
  a page contained failed with `database disk image is malformed`, and a deleted page's
  terms could match an unrelated new row. The triggers now use FTS5's `'delete'` command,
  and BookStack items are upserted with `ON CONFLICT DO UPDATE`, because
  `INSERT OR REPLACE` did not fire the delete trigger at all.
- **Books, chapters and pages with the same id coexist.** `bookstack_content` declared
  `bookstack_id` unique on its own, while BookStack numbers each type separately, so
  syncing book 1 replaced page 1. The key is now `(bookstack_id, type)`.
- **A resync that cannot load an item no longer prunes it.** API errors are turned into
  empty results by the client, and `sync_book()` caught its own exceptions, so a book or
  page that timed out during the walk counted as deleted. Every book, chapter and page
  that fails to load now counts as an error, and any error skips the prune.
- **Conversations keep their history.** The widget sent its session id only as the
  `X-Widget-Session` header and ignored the id in the answer; the server read the id from
  the body and only accepted ids it had issued. Every message started a new session, so
  the model never saw an earlier turn, and each message left one more session in memory.
  The server now reads the header as well, and both widgets store the id it returns.
- **The Compose stack runs with the system prompt.** `docker-compose.yml` passes
  `CHATBOT_SYSTEM_PROMPT` through as an empty string when it is unset, and
  `os.getenv(name, default)` returns that empty string, so the model got no instructions
  at all. An empty value now means the built-in prompt.
- **Questions containing an upper-case `NOT`, `AND` or `NEAR` find wiki content.** Search
  terms reached FTS5 as bare words, so these became operators, the query failed with a
  syntax error, and every BookStack search returned nothing. All terms are now quoted
  (`query_processor/preprocessor.py`). The exact-phrase strategy, which quoted an
  `OR`-joined string, and the proximity strategy, which built invalid `NEAR()` syntax
  from hyphenated keywords, match again. A question without any searchable word skips
  the search instead of searching for the German word "dokument".
- **The model sees the matching wiki text, not a 50-token snippet.** Wiki hits reached
  the prompt as the FTS5 `snippet()` of the match; they now carry the full text of their
  best chunks, up to three per page. The page-level and chunk-level hits of one page
  share an id and merge in the fusion, so a page takes one context slot instead of two.
- **Uploaded documents are indexed and deletable.** Indexing wrote to `kb_chunk_stats`
  and `kb_search_fts`, and deleting to `kb_search_fts`; no schema ever created either
  table, so every upload ended with `no such table` and no chunks, and every delete
  failed. The writes are gone. Deleting a document now also removes its chunks: the
  schema's `ON DELETE CASCADE` never applied, because SQLite enforces it only with
  `PRAGMA foreign_keys=ON`.
- **Chunks stay bounded, and short sentences survive.** Both chunkers collapsed all
  whitespace before splitting on paragraphs, so a page of list items or table rows
  without sentence punctuation became one chunk of any size (a list of 1,200 items came
  out as a single chunk; it now yields 11 chunks of at most 798 words). Sentences of ten
  characters or less, such as "Port 8080.", were dropped. HTML cleaning now keeps one
  line per block element.
- **Chunk-search scores no longer favour the weakest matches.** `abs()` on the FTS5 rank
  followed by `1 / (1 + rank)` inverted the order. Every strategy now scores a hit as its
  weight times its bm25 relevance relative to the best hit, where wiki hits used to get
  a constant. The multi-strategy bonus counts each strategy once per document, and a
  keyword search attaches a snippet to every document instead of only the first.
- **`kb_admin.py` runs.** It put the repository root on `sys.path` instead of `chatbot/`
  and exited with `No module named 'documents'` unless `PYTHONPATH=chatbot` was set. On a
  fresh stack it now creates the missing tables instead of exiting. `documents upload`
  and `bulk upload` index what they upload; `index rebuild --force` reindexes instead of
  only deleting the index; `bulk reindex` picks up pending documents; `index optimize`
  commits before `VACUUM`; `index status` counts pending documents; `stats performance`
  reads the `chunk_text` column that exists; `--skip-existing` compares SHA-256 hashes as
  stored instead of MD5; the health check tests the real upload directory and runs FTS5's
  integrity check.
- **A fresh Docker volume is writable.** The image created `/app/data` as root, a new
  named volume took over that ownership, and the container, running as uid 1000, failed
  with `unable to open database file` (reproduced with the v0.2.0 Dockerfile). The
  directory now belongs to uid 1000 and the image runs as that user.
- **The widget reaches the API on BookStack instances with a port.** In production the
  widget built its URL from protocol and hostname, dropping the port, so BookStack on
  `https://wiki.example.com:8443` posted to port 443.
- **`LOG_LEVEL` and `TZ` take effect.** Logging was fixed at `INFO` and log times at
  Europe/Berlin regardless of either variable.

### Security
- **Forged `X-Forwarded-For` headers no longer pass the allow-list or dodge the rate
  limit.** The client address was the leftmost header entry, which the client controls;
  with port 8888 published, anyone could name an allowed address, and because stock
  BookStack does not sign webhooks, that was enough to delete index content through a
  fake `book_delete`. The address is now the connecting one; behind a reverse proxy,
  `TRUSTED_PROXY_HOPS` tells werkzeug's `ProxyFix` how many proxy entries to trust, from
  the right.
- **The standalone chat page accepts page context only from BookStack.** Its `message`
  listener took `bookstack-context` from any origin, so a page framing `/chat/widget`
  could put text into the prompt. It now checks the origin of `BOOKSTACK_EXTERNAL_URL`.
- **Error responses no longer carry exception text.** The widget API returned `str(e)`
  as `details`, and the Azure provider returned raw error messages as chat answers,
  which also went into the conversation history. Visitors now see a short notice; the
  detail is logged, and a failed turn is not stored.
- **Timeouts bound every outbound call.** BookStack API requests had none, and Azure
  calls ran with the SDK's 600 s default and two internal retries plus six tenacity
  attempts, while waitress serves with four threads. BookStack calls now time out after
  30 s, Azure attempts after 60 s with three attempts in total, and the tenacity handlers
  see the real exception (`reraise=True`) instead of `RetryError`.
- **Sessions and rate-limit counters are thread-safe and bounded.** Both lived in plain
  dicts shared by the waitress threads; session cleanup iterated while other threads
  inserted, and neither structure ever shrank. Both are now guarded by locks; sessions
  are capped at 5000, and the rate limiter forgets clients idle for a minute.
- **`python app.py` binds to 127.0.0.1.** It ran Flask's debugger on all interfaces.

### Added
- **A test suite that runs in CI.** 63 pytest tests under `tests/` cover chunking, FTS5
  query building, the sync service, the webhook endpoint, the widget API and end-to-end
  retrieval against a temporary database and a fake BookStack API; `lint.yml` runs them
  on every push. The two former scripts were not tests: one failed on import (it added
  `tests/chatbot` to the path), the other needed a live BookStack and always exited 0.
  The live check survives as `pytest -m integration`.
- **`TRUSTED_PROXY_HOPS`** (default `0`) and **`OLLAMA_MODEL`** (default
  `mistral:latest`; the model used to be fixed in code).
- **The schema repairs itself at startup.** `startup_migrations.py` creates the BookStack
  index and the knowledge-base tables, replaces an index built by an older version, and
  warns when the BookStack index is empty. `kb_admin.py` and `scripts/init_kb_schema.py`
  use the same code.
- **`/health` reports the version**, read from the new `chatbot/version.py`.

### Changed
- **One chunking implementation.** `chatbot/utils/text_chunking.py` replaces the two
  near-identical copies in `chatbot/bookstack/chunking.py` and
  `chatbot/documents/knowledge_base/services/chunking.py`, which keep their own
  defaults (800/150/80 and 1000/200/100 words).
- **Retrieval searches the question only.** The widget's page text (up to 20,000
  characters) was appended to the search query, so keyword extraction picked terms from
  the page rather than from the question, and the page then went into the prompt twice.
  It now goes into the prompt once, in full, as context.
- **English stopwords and intent patterns** join the German ones, so English questions
  no longer search for "what", "the" or "how". Keywords keep digits ("error 404").
- **The context block is English** ("Relevant information from the knowledge base",
  "Document", "Excerpt"), matching the English system prompt, and is left out when no
  document contributed an excerpt instead of sending an empty heading.
- **`bulk cleanup` only reports unless called with `--apply`**; it used to delete by
  default. It removes chunks of documents that no longer exist, no longer those of
  deactivated ones, and deletes old deactivated documents with their files and tags.
- **Upload types are what text can be extracted from**: `.pdf`, `.docx`, `.txt`, `.md`,
  `.markdown`. `ALLOWED_EXTENSIONS` listed `doc`, `csv`, `xlsx` and `xls` as well, which
  the extraction never handled, while `kb_admin.py` checked a list of its own.
- **Ollama requests a 16k-token context window** instead of 128k, and no longer forces
  `num_gpu=40` for every model whose name contains "mistral"; both were settings of the
  machine the code came from.
- **CI:** `mypy` gates the build (93 errors on v0.2.0, 0 now), `ruff` and `black` cover
  `samples/`, and the `shellcheck` job is gone: there is no shell script in the
  repository for it to check.
- **The documentation follows the code.** Setup gained the webhook step and the initial
  resync that were missing, `docker/nginx-example.conf` routes `/chat/api/` to the
  chatbot, and `SECURITY.md` supports the current 0.x line instead of a 1.x that does
  not exist.

### Removed
- **Widget chat logging.** It meant to store every message with IP address and user
  agent, but its migration file was never in the repository, so the tables did not exist
  and every write failed silently. Removed rather than repaired: the documentation
  promises that the backend keeps no user record. `kb_admin.py stats usage` and the query
  statistics in `stats overview`, which read yet another table that nothing wrote, went
  with it.
- **Domain code from the original deployment**: the ICD-10 code boost and medical
  synonym expansion in the query preprocessor (on by default; "x86 build fails" became
  `X86 OR x86 OR build OR fails`), and psychology-specific synonyms. `SYNONYMS` ships
  empty for your own entries.
- **Dead code; the deleted files alone held 3,883 lines**: the unreferenced CSS and
  JavaScript under `chatbot/static/`, `export.py`, `keyword_extraction.py`, `document_strategy.py`,
  `suggestions.py`, three empty shim modules shadowed by same-named packages,
  `utils/database.init_database()` with its outdated schema, streaming and model-catalogue
  code in the LLM layer, and `bookstack-integration/api_client.py` and
  `theme-functions.php`, a stale copy of the chatbot's API client and an empty stub.
- **`FLASK_ENV`**, which nothing read and Flask 3 no longer supports, and the
  undocumented `WINDOWS_HOST_IP` CORS origin.

### Upgrade notes

The BookStack index built by earlier versions has the wrong key and corrupting
triggers. The first start of this version drops it and logs
`Dropped the BookStack index built by an older version`; rebuild it from BookStack:

    docker compose -f docker/docker-compose.yml up -d --build
    docker compose -f docker/docker-compose.yml exec chatbot python resync.py --full-resync

Uploaded documents keep their rows; their FTS index is repaired in place at startup.
Chunking changed for them too, so reindex once:

    DATABASE_PATH=/path/to/chatbot.db python3 scripts/kb_admin.py index rebuild --force

Re-paste `bookstack-integration/widget.html` into BookStack's custom HTML head: the
session and URL fixes live in that file.

Behind a reverse proxy, set `TRUSTED_PROXY_HOPS=1`, otherwise the allow-list and the
rate limit see the proxy's address for every visitor. Make sure port 8888 is not
reachable around the proxy, and route `/chat/api/` as `docker/nginx-example.conf` shows.
`ALLOWED_VPN_IPS` must include the Docker network (e.g. `172.16.0.0/12`) for webhooks
to pass.

Log times now follow `TZ`, which `docker-compose.yml` defaults to UTC; they were
Europe/Berlin regardless. A `chatbot_data` volume created by an older image is still
owned by root; if the chatbot logs `unable to open database file`, fix it once:

    docker compose -f docker/docker-compose.yml run --rm --user root chatbot chown -R 1000:1000 /app/data

`kb_admin.py bulk cleanup` needs `--apply` to delete. `kb_admin.py stats usage`, the
`FLASK_ENV` and `WINDOWS_HOST_IP` variables and the `PYTHONPATH=chatbot` prefix are no
longer needed or read.

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
