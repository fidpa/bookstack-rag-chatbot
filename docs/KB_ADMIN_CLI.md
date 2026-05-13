# Knowledge-Base Admin CLI

`scripts/kb_admin.py` manages the **independent knowledge base** (`kb_*` tables in `chatbot.db`) — the one that holds uploaded documents (PDFs, DOCX, Markdown, text). For BookStack content, no CLI is needed; webhooks handle it automatically.

## Quick Reference

```bash
# Inside the chatbot container:
docker compose -f docker/docker-compose.yml exec chatbot \
  python3 /app/scripts/kb_admin.py <command> [options]

# Or on the host, with the venv activated:
python3 scripts/kb_admin.py <command> [options]
```

## Commands

### `health-check`

Verify the chatbot is reachable, the database is writable, and the FTS5 tables exist.

```bash
kb_admin.py maintenance health-check
```

Exit code `0` = healthy. Anything else = check the output.

### `upload`

Upload one or more documents into the knowledge base. Supported types: `.pdf`, `.docx`, `.md`, `.txt`.

```bash
kb_admin.py document upload ./my-doc.pdf
kb_admin.py document upload ./docs/*.md --tag policy --tag onboarding
```

Options:

- `--tag TAG` — attach a tag (repeatable). Tags are filterable at query time.
- `--title TITLE` — override the auto-detected title.
- `--collection NAME` — group documents into a named collection.
- `--force` — re-upload an existing document (overwrites the prior version).

### `list`

List documents currently in the knowledge base.

```bash
kb_admin.py document list                      # all documents
kb_admin.py document list --tag policy          # filter by tag
kb_admin.py document list --collection onboarding
```

Output is a table with: id, title, type, size, tags, indexed-at.

### `delete`

Remove a document and all its chunks.

```bash
kb_admin.py document delete <doc-id>
kb_admin.py document delete --all --collection demo   # delete a whole collection
```

### `reindex`

Re-chunk and re-index a document. Useful after changing chunking parameters in `config.py`.

```bash
kb_admin.py document reindex <doc-id>
kb_admin.py document reindex --all              # re-index everything (slow)
```

### `stats`

Overview of the knowledge base.

```bash
kb_admin.py stats overview
```

Reports document count, chunk count, total tokens, oldest document, newest document, and per-tag counts.

### `maintenance health-check`

End-to-end health probe: DB connectivity, table integrity, FTS index/chunk
parity, storage access, importable service modules.

```bash
kb_admin.py maintenance health-check
```

Returns a percentage and a list of issues + recommendations.

## Common Workflows

### Bulk-import a directory of PDFs

```bash
for f in /path/to/docs/*.pdf; do
  python3 scripts/kb_admin.py document upload "$f" --tag bulk-import
done
```

### Clean up a failed batch

```bash
kb_admin.py document list --tag bulk-import --format ids \
  | xargs -n1 python3 scripts/kb_admin.py document delete
```

### Validate index integrity after a restore

```bash
kb_admin.py maintenance health-check
kb_admin.py stats overview                       # sanity-check counts
kb_admin.py debug search "$(head -c40 /path/to/known/doc.txt)"  # known content
```

## Notes

- The CLI talks directly to the SQLite database. Make sure the chatbot container is **stopped** before running long-running commands like `reindex --all`, otherwise you'll hit SQLite's single-writer lock.
- Document IDs are UUIDs, not auto-increment integers. Always copy from the `list` output rather than guessing.
- Logs go to the container's stdout. Run with `--verbose` for detailed traces.
