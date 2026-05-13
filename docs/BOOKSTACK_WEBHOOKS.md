# BookStack Webhooks

The chatbot keeps its RAG index in sync with BookStack via webhooks. This page documents the 16 events the chatbot listens to, what each one does, and how to configure them.

## Configuring Webhooks in BookStack

In BookStack:

1. Sign in as admin.
2. Go to **Settings → Webhooks → Create Webhook**.
3. Set:
   - **Name**: `chatbot`
   - **Endpoint**: `http://chatbot:8888/webhook/bookstack` (Docker-internal hostname)
   - **Events**: select all 16 events listed below.
4. Save.

> **Note**: BookStack v25.07 does **not** sign webhooks with HMAC. The chatbot enforces authenticity via the IP allow-list — make sure your reverse proxy strips spoofed source IPs. See [SECURITY.md](SECURITY.md).

## The 16 Events

BookStack v25.07 emits underscore-cased event names. The list below matches
`RELEVANT_EVENTS` in `chatbot/bookstack/webhooks.py`.

| Event | Triggered when… | RAG-index action |
|---|---|---|
| `page_create` | A page is created | Fetch the page, chunk, index |
| `page_update` | A page's content or metadata changes | Re-fetch, re-chunk, replace |
| `page_delete` | A page is deleted | Remove all chunks for that page |
| `page_move` | A page is moved between books/chapters | Update parent metadata |
| `page_restore` | A page is restored from the bin | Treat as `page_create` |
| `chapter_create` | A chapter is created | Index chapter metadata (used for source URLs) |
| `chapter_update` | A chapter is renamed or its content metadata changes | Update metadata; re-index descendant pages |
| `chapter_delete` | A chapter is deleted | Remove descendant pages from the index |
| `chapter_move` | A chapter is moved between books | Update parent links; re-index descendant pages |
| `book_create` | A book is created | Index book metadata |
| `book_update` | A book is renamed or metadata changes | Update metadata; re-index descendant pages |
| `book_delete` | A book is deleted | Remove descendant pages from the index |
| `book_sort` | A book's chapter/page ordering changes | Refresh parent links |
| `bookshelf_create` | A bookshelf is created | Index bookshelf metadata |
| `bookshelf_update` | A bookshelf is updated | Update metadata |
| `bookshelf_delete` | A bookshelf is deleted | Index entries unaffected (bookshelves are virtual) |

## Event Flow

```
BookStack edit
    │
    ▼
BookStack webhook  ──HTTP POST──►  chatbot /webhook/bookstack
                                        │
                                        ▼
                             Validate event type & IP
                                        │
                                        ▼
                              For page_*, book_*, chapter_*:
                                        │
                                        ▼
                              GET BookStack API for affected content
                                        │
                                        ▼
                              Chunk → upsert into bookstack_chunks_fts
                                        │
                                        ▼
                              200 OK
```

The chatbot returns 200 even if it decides to ignore the event, so BookStack doesn't retry.

## Failure Modes

### "Webhook delivery failed" in BookStack logs

Most common causes:

- The chatbot container is not running. Check `docker compose ps`.
- The Docker network is not shared. Both services must be on `bookstack-network`.
- The chatbot rejected the IP. Check chatbot logs for "denied by IP allow-list".

### Webhook fires but index doesn't update

- The BookStack API token in `.env` is missing or invalid. The chatbot can receive the webhook but cannot fetch the affected page back.
- Fix: regenerate the token in BookStack and restart `chatbot`.

### Index drifts from BookStack over time

This can happen if webhooks were failing silently for a while. You can rebuild the index from scratch:

```bash
docker compose -f docker/docker-compose.yml exec chatbot \
  python -m chatbot.bookstack.sync_service --full-resync
```

This walks the entire BookStack API and re-indexes everything. Safe to run anytime; takes ~1 minute per 1 000 pages.

## Testing Webhooks Manually

Send a fake event from the host shell:

```bash
curl -X POST http://localhost:8888/webhook/bookstack \
  -H 'Content-Type: application/json' \
  -d '{
    "event": "page_update",
    "text": "Manual test",
    "related_item": {"id": 1, "name": "Test"}
  }'
```

The chatbot's logs should show it received and processed the event.
