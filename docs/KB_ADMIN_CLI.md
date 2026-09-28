# Knowledge-Base Admin CLI

`scripts/kb_admin.py` manages the **independent knowledge base**, the `kb_*` tables in
`chatbot.db` that hold uploaded documents. BookStack content needs no CLI; webhooks
keep it in sync.

## Running it

The script is **not in the container image**. `docker/docker-compose.yml` builds the
chatbot with `context: ../chatbot`, so only the `chatbot/` directory lands in `/app`;
`scripts/` stays on the host. It needs the chatbot's dependencies and runs from
anywhere:

```bash
pip install -r chatbot/requirements.txt
DATABASE_PATH=/path/to/chatbot.db python3 scripts/kb_admin.py <command> <action> [options]
```

The script puts `chatbot/` on its import path itself. Before v0.3.0 it added the
repository root instead and failed with `Import error: No module named 'documents'`
unless `PYTHONPATH=chatbot` was set.

`DATABASE_PATH` must point at the database the chatbot uses. In the container that is
`/app/data/chatbot.db` on the `chatbot_data` volume; bind-mount the volume or work on
a copy. Uploaded files are stored in `knowledge_base/` next to the database file. On
first use the CLI creates any missing tables, so it also works on a fresh stack.

## Command Tree

```
kb_admin [--version] [--format {table,json}]
├── documents  list | upload | show | update | delete
├── bulk       upload | reindex | cleanup
├── index      status | rebuild | optimize
├── stats      overview | performance
└── maintenance health-check
```

`--format` is global and has to come **before** the subcommand:
`kb_admin.py --format json documents list`.

## `documents`

```
usage: kb_admin documents list [-h] [--status {active,inactive,all}] [--limit LIMIT]

  --status {active,inactive,all}
                        Filter by status (default: active)
  --limit LIMIT         Maximum number of results (default: 50)

usage: kb_admin documents upload [-h] --file FILE [--title TITLE] [--tags TAGS]
                                 [--description DESCRIPTION]

  --file FILE           File path to upload
  --title TITLE         Document title (default: filename)
  --tags TAGS           Comma-separated tags
  --description DESCRIPTION
                        Document description

usage: kb_admin documents show [-h] --id ID [--chunks]

  --id ID     Document ID
  --chunks    Include chunk information

usage: kb_admin documents update [-h] --id ID [--title TITLE] [--tags TAGS]
                                 [--description DESCRIPTION]

usage: kb_admin documents delete [-h] --id ID [--confirm]

  --id ID     Document ID
  --confirm   Confirm deletion
```

`upload` takes exactly one file. For a directory, use `bulk upload`. The table that
`list` prints has the columns ID, Title, Type, Size, Status, Uploaded; tags are not in
it, use `documents show --id`.

`upload` stores the file and indexes it in one go: the document is searchable when
the command returns, and a failed text extraction is reported as a failed upload
(the row stays, with `chunking_status = 'failed'`, for `bulk reindex` to retry).

Accepted extensions come from `ALLOWED_EXTENSIONS` in
`chatbot/documents/knowledge_base/validators.py`: `.pdf`, `.docx`, `.txt`, `.md`,
`.markdown`, the types text can be extracted from.

## `bulk`

```
usage: kb_admin bulk upload [-h] --directory DIRECTORY [--recursive]
                            [--extensions EXTENSIONS] [--batch-size BATCH_SIZE]
                            [--skip-existing] [--tags TAGS]

  --directory DIRECTORY
                        Directory to upload
  --recursive           Include subdirectories
  --extensions EXTENSIONS
                        File extensions (comma-separated)
  --batch-size BATCH_SIZE
                        Parallel uploads
  --skip-existing       Skip existing files
  --tags TAGS           Tags for all uploaded files

usage: kb_admin bulk reindex [-h] [--force] [--batch-size BATCH_SIZE]

  --force               Force reindex all documents
  --batch-size BATCH_SIZE
                        Batch size

usage: kb_admin bulk cleanup [-h] [--apply] [--dry-run] [--older-than OLDER_THAN]

  --apply               Delete what was found (default: only report it)
  --dry-run             Only report what would be deleted (the default; kept for scripts)
  --older-than OLDER_THAN
                        Delete items older than N days
```

`--extensions` defaults to `pdf,docx,txt,md`. `--skip-existing` compares filename and
SHA-256 content hash against active documents.

`bulk reindex` without `--force` picks up documents that are pending, failed or were
interrupted; with `--force` it reindexes every active document.

`bulk cleanup` reports by default and deletes only with `--apply`. It finds chunks whose
document row no longer exists, and deactivated documents older than `--older-than`
days (default 30); the latter are deleted with their file, chunks and tags. Chunks of
a merely deactivated document are left alone, so reactivating it needs no reindex.
Before v0.3.0 the command deleted by default, and removed the chunks of deactivated
documents.

## `index`

```
usage: kb_admin index [-h] {status,rebuild,optimize} ...

usage: kb_admin index rebuild [-h] [--document-id DOCUMENT_ID] [--force]

  --document-id DOCUMENT_ID
                        Rebuild specific document
  --force               Force full rebuild
```

`rebuild --document-id` reindexes one document; without it, `rebuild` does what
`bulk reindex` does (pending and failed documents, or all with `--force`).
`optimize` rebuilds the knowledge-base FTS index from `kb_chunks`, merges the segments
of all three FTS indexes, updates the planner statistics and vacuums the file.
`status` and `optimize` take no options.

## `stats`

```
usage: kb_admin stats [-h] {overview,performance} ...
```

Neither takes options. `stats usage` and the query statistics in `overview` read a
chat log table that nothing ever wrote to; they were removed in v0.3.0, along with the
chat logging itself.

## `maintenance health-check`

Five checks: database connectivity, table integrity (`kb_documents`, `kb_chunks`,
`kb_chunks_fts`), index health (FTS5's own `integrity-check` of `kb_chunks_fts`
against `kb_chunks`), write access to the upload directory, and importability of the
two service modules. The output is a score (`checks_passed / 5`) as a percentage, plus
the issues and recommendations collected along the way. The exit status is `1` when
any check found an issue.

## Common Workflows

### Import a directory of PDFs

```bash
python3 scripts/kb_admin.py bulk upload \
  --directory /path/to/docs --extensions pdf --tags bulk-import
```

### Find a document ID, then act on it

IDs are auto-increment integers (`--id` is `type=int`), not UUIDs.

```bash
python3 scripts/kb_admin.py --format json documents list --limit 200
python3 scripts/kb_admin.py documents show --id 42 --chunks
python3 scripts/kb_admin.py documents delete --id 42 --confirm
```

`delete` without `--confirm` does not delete.

### Check integrity after a restore

```bash
python3 scripts/kb_admin.py maintenance health-check
python3 scripts/kb_admin.py index status
python3 scripts/kb_admin.py stats overview
```

## Notes

- The CLI writes to the same SQLite file as the running container. Stop the chatbot
  before a `bulk reindex` or an `index rebuild --force`, or you will meet SQLite's
  single-writer lock. Reads are fine while it runs.
- There is no `search` and no `debug` subcommand, and no `--verbose` flag. Diagnostic
  output goes to stdout; `--format json` gives you the machine-readable form of the
  same response object.
- `kb_admin --version` reports the release, read from `chatbot/version.py`.
