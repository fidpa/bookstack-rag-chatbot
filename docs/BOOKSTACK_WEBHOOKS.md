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
5. Make sure the webhook's source address passes the allow-list: deliveries come from
   the BookStack container, so `ALLOWED_VPN_IPS` must include the Docker network
   (for example `172.16.0.0/12`) or be empty.

Webhooks only report changes from now on. Content that already existed is indexed
once with a full resync (see below).

> **Authenticity**: BookStack v25.07 does not sign webhook payloads, so the endpoint's
> protection is the IP allow-list. It checks the connecting address and ignores
> `X-Forwarded-For` unless `TRUSTED_PROXY_HOPS` is set, so a forged header does not
> get a request past it. `chatbot/bookstack/webhooks.py` does carry an HMAC-SHA256 check, and setting
> `BOOKSTACK_WEBHOOK_SECRET` switches it on, but it then **requires** an
> `X-BookStack-Signature` header that stock BookStack never sends. Leave the variable
> empty unless you run a build that signs. See [SECURITY.md](SECURITY.md).

## The 13 Events

The list matches `RELEVANT_EVENTS` in `chatbot/bookstack/webhooks.py`. The handler
reads the affected item from `related_item.id`, where BookStack's `WebhookFormatter`
puts it, and dispatches on the event name: the three delete events remove from the
index, every other event re-syncs the item. A payload without `related_item.id` is
answered with 400.

Before v0.3.0 the handler read `related.<type>.id`, a key BookStack never sends, so
every real delivery was acknowledged and changed nothing.

| Event | Handler branch | What runs |
|---|---|---|
| `page_create` | page | `sync_page(id)`: fetch, clean, chunk, upsert; the payload's `url` is stored as the page link |
| `page_update` | page | `sync_page(id)` |
| `page_move` | page | `sync_page(id)` |
| `page_restore` | page | `sync_page(id)` |
| `page_delete` | page | `remove_page_from_index(id)` |
| `chapter_create` | chapter | `sync_chapter(id)`: store chapter metadata, then `sync_page` for every page in it |
| `chapter_update` | chapter | `sync_chapter(id)` |
| `chapter_move` | chapter | `sync_chapter(id)` |
| `chapter_delete` | chapter | `remove_chapter_from_index(id)`: the chapter and every page carrying its `chapter_id` |
| `book_create` | book | `sync_book(id)`: store book metadata, then every chapter and page listed in the book's `contents` |
| `book_update` | book | `sync_book(id)` |
| `book_sort` | book | `sync_book(id)` |
| `book_delete` | book | `remove_book_from_index(id)`: the book, its chapters and every page carrying its `book_id` |

Each event also invalidates the API client's cache entries for the affected item and
for its parent book and chapter, so a following book sync sees the change.

### Deleting a chapter or a book

All three delete events remove content. The API is no help once the item is gone, so
the removal works off the index itself: `sync_page()` records `book_id` and `chapter_id`
with every page, and the two removal methods delete by those columns. The FTS tables
follow through the `AFTER DELETE` triggers on `bookstack_content` and
`bookstack_chunks`, which since v0.3.0 remove the deleted terms with FTS5's `'delete'`
command; before that, deleted and replaced text stayed searchable.

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
                             Read related_item.id  ──missing──►  400
                                        │
                                        ▼
                             GET BookStack API for the affected content
                                        │
                                        ▼
                             Upsert into bookstack_content, replace chunks
                             (FTS tables follow via triggers)
                                        │
                                        ▼
                             200 {"status":"processed"}
```

`processed` means the handler reached the end without an exception, not that the index
changed: an API fetch that comes back empty (token invalid, item gone) ends here too and
is only visible in the log. A missing `related_item.id` is a 400; an unhandled exception
a 500.

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
- The event is not subscribed in BookStack, or the page is a draft (drafts are not
  indexed until published).

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

The walk follows the `contents` list of every book, and pages through the book list
in batches of 500. The pruning step is what repairs a drifted index, and it is
deliberately cautious: it runs only after a walk in which every book, chapter and page
loaded. A failed API call therefore leaves the index untouched rather than emptying
it, because "BookStack reports nothing" and "BookStack is unreachable" look the same
from here. Pass `--no-prune` to add and update only.

The command writes to the same SQLite file as the running app, so prefer a quiet moment.
It exits non-zero when the walk hit errors.

## Testing Webhooks Manually

Send the shape BookStack sends, from an allowed IP:

```bash
curl -X POST http://localhost:8888/webhook/bookstack \
  -H 'Content-Type: application/json' \
  -d '{"event": "page_update", "related_item": {"id": 1}}'
```

A `{"status":"processed"}` response only says the handler ran; check the chatbot log for
the sync itself. To verify connectivity alone, without a payload and without the
allow-list, `GET /webhook/bookstack/test` answers with the accepted event list.
