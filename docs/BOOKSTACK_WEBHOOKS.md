# BookStack Webhooks

The chatbot keeps its RAG index in sync with BookStack via webhooks. This page
documents the 14 events it listens to, what the handler actually does with each, and
how to configure them.

## Configuring Webhooks in BookStack

1. Sign in as admin.
2. Go to **Settings → Webhooks → Create Webhook**.
3. Set:
   - **Name**: `chatbot`
   - **Endpoint**: `http://chatbot:8888/webhook/bookstack` (Docker-internal hostname)
   - **Events**: select the 14 events listed below.
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

## The 14 Events

The list matches `RELEVANT_EVENTS` in `chatbot/bookstack/webhooks.py`. The handler
reads the affected item from `related_item.id`, where BookStack's `WebhookFormatter`
puts it, and dispatches on the event name: the three delete events remove from the
index right away, every other event is queued and re-syncs the item a moment later
(see "When the sync runs" below). A payload without `related_item.id` is answered with
400, except `recycle_bin_restore`, which carries no item.

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
| `recycle_bin_restore` | any | no item in the payload (only the restore URL): a walk over the whole wiki that adds and updates but does not prune, five seconds later |

The API client keeps no cache: every sync reads BookStack as it is at that moment. (Up to
v0.3.0 it cached items for five minutes, and a book sync could then re-index a page in its
old chapter.)

### Deleting a chapter or a book

All three delete events remove content. The API is no help once the item is gone, so
the removal works off the index itself: `sync_page()` records `book_id` and `chapter_id`
with every page, and the two removal methods delete by those columns. The FTS tables
follow through the `AFTER DELETE` triggers on `bookstack_content` and
`bookstack_chunks`, which since v0.3.0 remove the deleted terms with FTS5's `'delete'`
command; before that, deleted and replaced text stayed searchable.

Before v0.2.0 this did not happen: `chapter_delete` and `book_delete` ran the same sync
as a rename, found nothing, and left the pages searchable, so the chatbot could cite a
page that no longer existed. An index that drifted that way is repaired by a full
resync, below.

### When the sync runs

BookStack sends `page_create`, `chapter_create`, `page_move` and `book_sort` from inside
the database transaction that makes the change, and with its default queue
(`QUEUE_CONNECTION=sync`) before it has answered the editor's request. A chatbot that reads
the item back at that moment sees the state from before the commit (checked against
BookStack 25.07.3): the new page as a draft with the title "New Page", the new chapter as
`404`, the moved page in its old chapter. So the endpoint does not sync inside the request:

1. The deletions (`page_delete`, `chapter_delete`, `book_delete`) need nothing from
   BookStack and are applied at once (`200`, `"status": "processed"`). The same removal is
   queued once more, so that a sync job that read the item just before BookStack deleted it
   cannot write it back.
2. Every other event is queued (`202`, `"status": "queued"`). One background thread
   (`chatbot/bookstack/webhook_worker.py`) runs the jobs in order. A job starts
   `SYNC_DELAY_SECONDS` (2 s) after the event, reads the item from the API and updates the
   index.
3. If a new item is not there yet (after `page_create`, `chapter_create` or `book_create`
   the API answers `404`, or a page that BookStack reported as published still reads as a
   draft), the job is repeated after 3, 6 and 12 seconds (`RETRY_DELAYS`), then given up on
   with a `Webhook job … gave up` warning in the log. Any other event is read once: an item
   that already existed and cannot be read is deleted or hidden from the token's user. A
   `gave up` warning is therefore also what a page looks like that the token's user may not
   see (restricted pages stay out of the index on purpose), so the warning alone is not a
   fault.
4. `recycle_bin_restore` names no item and arrives before the restore happens, so its job
   walks the whole wiki after `RESTORE_DELAY_SECONDS` (5 s), without pruning. The walk is
   repeated only if no book could be read at all; items that fail to load are logged and
   left to the next full resync. On a large wiki the walk takes a while (one API request
   per book, chapter and page), and the jobs queued behind it wait for it.

The constants live in `chatbot/bookstack/webhooks.py`. At most 500 jobs wait at a time; an
event that finds the queue full is answered with `503` and logged, and the next full
resync repairs the index. Jobs that are queued when the container stops are lost the same
way. Two details for operators: the queue lives in the chatbot process only, and BookStack
sees `202` as soon as the event is accepted, so a failed sync shows up in the chatbot log,
not in BookStack.

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
                        ┌───────────────┴───────────────┐
                     delete events                  all others
                        │                               │
                        ▼                               ▼
               remove from the index          202 {"status":"queued"}
               200 {"status":"processed"}             │
                                                       ▼  worker, 2 s later
                                          GET BookStack API for the item
                                          not visible yet? retry after 3, 6, 12 s
                                                       │
                                                       ▼
                                          Upsert into bookstack_content, replace chunks
                                          (FTS tables follow via triggers)
```

`queued` means the event was accepted, not that the index changed: an API fetch that keeps
coming back empty (token invalid, item gone) ends in `Webhook job … gave up` in the log and
nowhere else. A missing `related_item.id` is a 400; an unhandled exception a 500; a full
queue a 503.

## Failure Modes

### "Webhook delivery failed" in BookStack logs

- The chatbot container is not running. Check `docker compose --env-file .env -f docker/docker-compose.yml ps`.
- The Docker network is not shared. Both services must be on `bookstack-network`.
- The chatbot rejected the source IP. Look for `Denied <ip> (not in ALLOWED_VPN_IPS)` in
  the chatbot log.
- `BOOKSTACK_WEBHOOK_SECRET` is set against a BookStack that does not sign. Every
  delivery then gets a 401 and `Invalid webhook signature from …` in the log. Clear the
  variable.

### Webhook arrives, index does not change

The endpoint answers `queued` in this case too, so the log is the only witness: look for
`Webhook job … gave up` and for `BookStack API error` lines.

- The BookStack API token in `.env` is missing or invalid: the chatbot receives the
  event but cannot fetch the page back. Regenerate the token, put it into `.env` and recreate
  the container (`docker compose --env-file .env -f docker/docker-compose.yml up -d chatbot`;
  a plain `restart` keeps the old environment).
- The event is not subscribed in BookStack, or the page is a draft (drafts are not
  indexed until published).
- The job is still waiting: a sync starts two seconds after the event, and a new item can take
  up to about 20 seconds until BookStack shows it to the API (see "When the sync runs").

### Index drifts from BookStack over time

Webhooks that failed silently for a while, or content deleted under an older version,
leave the index out of step. `chatbot/resync.py` walks the whole BookStack API and
rebuilds it:

```bash
# What does the index hold right now? Changes no content (it does create the
# SQLite file and schema if they are missing, like any start of the app).
docker compose --env-file .env -f docker/docker-compose.yml exec chatbot \
    python resync.py --dry-run

# Reindex everything and drop rows for content BookStack no longer reports.
docker compose --env-file .env -f docker/docker-compose.yml exec chatbot \
    python resync.py --full-resync
```

The walk follows the `contents` list of every book, and pages through the book list
in batches of 500. The pruning step is what repairs a drifted index, and it is
deliberately cautious: it runs only after a walk in which every book, chapter and page
loaded. A failed API call therefore leaves the index untouched rather than emptying
it, because "BookStack reports nothing" and "BookStack is unreachable" look the same
from here. Pass `--no-prune` to add and update only.

The command writes to the same SQLite file as the running app, so prefer a quiet moment.
It exits non-zero when the walk hit errors, including a book list that could not be
fetched at all (BookStack unreachable, token refused); up to v0.3.0 that case printed
`errors: 0` and exited 0.

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
