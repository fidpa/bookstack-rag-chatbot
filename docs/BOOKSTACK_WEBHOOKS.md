# BookStack Webhooks

The chatbot keeps its RAG index in sync with BookStack via webhooks. This page
documents the 13 events it listens to, what the handler actually does with each, and
how to configure them.

## Configuring Webhooks in BookStack

1. Sign in as admin.
2. Go to **Settings → Webhooks → Create Webhook**.
3. Set:
   - **Name**: `chatbot`
   - **Endpoint**: `http://chatbot:8888/webhook/bookstack` (Docker-internal hostname)
   - **Events**: select the 13 events listed below.
4. Save.

> **Authenticity**: BookStack v25.07 does not sign webhook payloads, so the endpoint's
> protection is the IP allow-list; make sure your reverse proxy strips spoofed source
> IPs. `chatbot/bookstack/webhooks.py` does carry an HMAC-SHA256 check, and setting
> `BOOKSTACK_WEBHOOK_SECRET` switches it on, but it then **requires** an
> `X-BookStack-Signature` header that stock BookStack never sends. Leave the variable
> empty unless you run a build that signs. See [SECURITY.md](SECURITY.md).

## The 13 Events

The list matches `RELEVANT_EVENTS` in `chatbot/bookstack/webhooks.py`. What happens
next does not branch per event: the handler tests the event name for the substrings
`page`, `chapter` and `book`, in that order, and calls one of three methods on
`ContentSyncService`. The ID comes from `related.page.id`, `related.chapter.id` or
`related.book.id` in the payload; when it is missing, the handler does nothing and
still answers `processed`.

| Event | Handler branch | What runs |
|---|---|---|
| `page_create` | page | `sync_page(id)`: fetch, clean, chunk, upsert |
| `page_update` | page | `sync_page(id)` |
| `page_move` | page | `sync_page(id)` |
| `page_restore` | page | `sync_page(id)` |
| `page_delete` | page | `remove_page_from_index(id)` |
| `chapter_create` | chapter | `sync_chapter(id)`: store chapter metadata, then `sync_page` for every page in it |
| `chapter_update` | chapter | `sync_chapter(id)` |
| `chapter_move` | chapter | `sync_chapter(id)` |
| `chapter_delete` | chapter | `remove_chapter_from_index(id)`: the chapter and every page carrying its `chapter_id` |
| `book_create` | book | `sync_book(id)`: store book metadata, then every chapter and every direct page |
| `book_update` | book | `sync_book(id)` |
| `book_sort` | book | `sync_book(id)` |
| `book_delete` | book | `remove_book_from_index(id)`: the book, its chapters and every page carrying its `book_id` |

Each branch also invalidates the API client's cache entry for the affected item.

### Deleting a chapter or a book

All three delete events remove content. The API is no help once the item is gone, so
the removal works off the index itself: `sync_page()` records `book_id` and `chapter_id`
with every page, and the two removal methods delete by those columns. The FTS tables
follow through the `AFTER DELETE` triggers on `bookstack_content` and
`bookstack_chunks`.

Before v0.1.5 this did not happen: `chapter_delete` and `book_delete` ran the same sync
as a rename, found nothing, and left the pages searchable, so the chatbot could cite a
page that no longer existed. An index that drifted that way is repaired by a full
resync, below.

### Bookshelf events are not in the list

`bookshelf_create`, `bookshelf_update` and `bookshelf_delete` were listed here until
v0.1.4 and never had an index operation: a bookshelf groups books, it holds no content
of its own. Subscribing to them in BookStack is harmless but pointless, and the endpoint
answers them with `ignored`.

## Event Flow

```
BookStack edit
    │
    ▼
BookStack webhook  ──HTTP POST──►  chatbot /webhook/bookstack
                                        │
                                        ▼
                             IP allow-list, then HMAC if configured
                                        │
                                        ▼
                             Event in RELEVANT_EVENTS?  ──no──►  200 {"status":"ignored"}
                                        │ yes
                                        ▼
                             Read related.<type>.id from the payload
                                        │
                                        ▼
                             GET BookStack API for the affected content
                                        │
                                        ▼
                             Chunk → upsert into bookstack_chunks_fts
                                        │
                                        ▼
                             200 {"status":"processed"}
```

`processed` means the handler reached the end without an exception, not that the index
changed. A payload with an unexpected shape, a missing ID or an API fetch that comes
back empty all end here. Only an unhandled exception produces a 500.

## Failure Modes

### "Webhook delivery failed" in BookStack logs

- The chatbot container is not running. Check `docker compose ps`.
- The Docker network is not shared. Both services must be on `bookstack-network`.
- The chatbot rejected the source IP. Look for `Denied <ip> (not in ALLOWED_VPN_IPS)` in
  the chatbot log.
- `BOOKSTACK_WEBHOOK_SECRET` is set against a BookStack that does not sign. Every
  delivery then gets a 401 and `Invalid webhook signature from …` in the log. Clear the
  variable.

### Webhook arrives, index does not change

The endpoint answers `processed` in this case too, so the log is the only witness.

- The BookStack API token in `.env` is missing or invalid: the chatbot receives the
  event but cannot fetch the page back. Regenerate the token and restart `chatbot`.
- The payload had no `related.<type>.id`. Custom senders and hand-rolled test requests
  usually trip on this.

### Index drifts from BookStack over time

Webhooks that failed silently for a while, or content deleted under an older version,
leave the index out of step. `chatbot/resync.py` walks the whole BookStack API and
rebuilds it:

```bash
# What does the index hold right now? Reads only.
docker compose -f docker/docker-compose.yml exec chatbot \
    python resync.py --dry-run

# Reindex everything and drop rows for content BookStack no longer reports.
docker compose -f docker/docker-compose.yml exec chatbot \
    python resync.py --full-resync
```

The pruning step is what repairs a drifted index, and it is deliberately cautious: it
runs only after a walk that finished without errors and returned content. A failed API
call therefore leaves the index untouched rather than emptying it, because "BookStack
reports nothing" and "BookStack is unreachable" look the same from here. Pass
`--no-prune` to add and update only.

The command writes to the same SQLite file as the running app, so prefer a quiet moment.
It exits non-zero when the walk hit errors.

## Testing Webhooks Manually

The payload has to carry the ID where the handler looks for it, and the request has to
come from an allowed IP:

```bash
curl -X POST http://localhost:8888/webhook/bookstack \
  -H 'Content-Type: application/json' \
  -d '{"event": "page_update", "related": {"page": {"id": 1}}}'
```

A `{"status":"processed"}` response only says the handler ran; check the chatbot log for
the sync itself. To verify connectivity alone, without a payload and without the
allow-list, `GET /webhook/bookstack/test` answers with the accepted event list.
