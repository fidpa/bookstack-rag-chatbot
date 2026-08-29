# Knowledge-Base Admin CLI

`scripts/kb_admin.py` manages the **independent knowledge base**, the `kb_*` tables in
`chatbot.db` that hold uploaded documents. BookStack content needs no CLI; webhooks
keep it in sync.

## Running it

The script is **not in the container image**. `docker/docker-compose.yml` builds the
chatbot with `context: ../chatbot`, so only the `chatbot/` directory lands in `/app`;
`scripts/` stays on the host. Run it from the repository root:

```bash
PYTHONPATH=chatbot python3 scripts/kb_admin.py <command> <action> [options]
```

`PYTHONPATH` is required. The script adds the repository root to `sys.path`, then
imports `documents.knowledge_base…` and `utils.database`, which live one level down
under `chatbot/`. Without it the script exits with `Import error: No module named
'documents'`.

It also needs the database. `DATABASE_PATH` points at `/app/data/chatbot.db` in the
container, which is the `chatbot_data` volume; set `DATABASE_PATH` to a host-readable
copy or path before running, or the first thing you see is a failed validation.
Startup checks that `kb_documents`, `kb_chunks` and `kb_tags` exist and exits `1`
otherwise.

## Command Tree

```
kb_admin [--version] [--format {table,json}]
├── documents  list | upload | show | update | delete
├── bulk       upload | reindex | cleanup
├── index      status | rebuild | optimize
├── stats      overview | usage | performance
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

Accepted extensions come from `ALLOWED_EXTENSIONS` in
`chatbot/documents/knowledge_base/validators.py`: `pdf`, `docx`, `doc`, `txt`, `md`,
`csv`, `xlsx`, `xls`. `MAX_FILE_SIZE` in the same file caps an upload at 20 MB.

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

usage: kb_admin bulk cleanup [-h] [--dry-run] [--older-than OLDER_THAN]

  --dry-run             Show what would be deleted
  --older-than OLDER_THAN
                        Delete items older than N days
```

`--extensions` defaults to `pdf,docx,txt,md`, which is narrower than what the validator
accepts; name the others explicitly if you want them. `bulk cleanup --older-than`
defaults to 30 days, so run `--dry-run` first.

## `index`

```
usage: kb_admin index [-h] {status,rebuild,optimize} ...

usage: kb_admin index rebuild [-h] [--document-id DOCUMENT_ID] [--force]

  --document-id DOCUMENT_ID
                        Rebuild specific document
  --force               Force full rebuild
```

`status` and `optimize` take no options.

## `stats`

```
usage: kb_admin stats [-h] {overview,usage,performance} ...

usage: kb_admin stats usage [-h] [--days DAYS]

  --days DAYS  Days to analyze
```

`--days` defaults to 30. `overview` and `performance` take no options.

## `maintenance health-check`

Five checks: database connectivity, table integrity (`kb_documents`, `kb_chunks`,
`kb_chunks_fts`), index health (chunk count against FTS entry count), storage access,
and importability of the two service modules. The output is a score
(`checks_passed / 5`) as a percentage, plus the issues and recommendations collected
along the way.

The exit status is `0` regardless of the score; read the output rather than `$?`. The
storage check resolves the relative path `data`, so it only passes when the CLI runs
from a directory that has one.

## Common Workflows

### Import a directory of PDFs

```bash
PYTHONPATH=chatbot python3 scripts/kb_admin.py bulk upload \
  --directory /path/to/docs --extensions pdf --tags bulk-import
```

### Find a document ID, then act on it

IDs are auto-increment integers (`--id` is `type=int`), not UUIDs.

```bash
PYTHONPATH=chatbot python3 scripts/kb_admin.py --format json documents list --limit 200
PYTHONPATH=chatbot python3 scripts/kb_admin.py documents show --id 42 --chunks
PYTHONPATH=chatbot python3 scripts/kb_admin.py documents delete --id 42 --confirm
```

`delete` without `--confirm` does not delete.

### Check integrity after a restore

```bash
PYTHONPATH=chatbot python3 scripts/kb_admin.py maintenance health-check
PYTHONPATH=chatbot python3 scripts/kb_admin.py index status
PYTHONPATH=chatbot python3 scripts/kb_admin.py stats overview
```

## Notes

- The CLI writes to the same SQLite file as the running container. Stop the chatbot
  before a `bulk reindex` or an `index rebuild --force`, or you will meet SQLite's
  single-writer lock. Reads are fine while it runs.
- There is no `search` and no `debug` subcommand, and no `--verbose` flag. Diagnostic
  output goes to stdout; `--format json` gives you the machine-readable form of the
  same response object.
- The CLI reports its own version (`kb_admin --version`), which tracks `CLI_VERSION` in
  the script and is bumped with the release.
