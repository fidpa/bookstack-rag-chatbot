# Troubleshooting

Symptom → likely cause → fix. Common issues first.

## The Chat Widget

### "I pasted `widget.html` and nothing shows up"

| Check | How |
|---|---|
| Did BookStack save the custom HTML? | Settings → Customisation → reload, content should still be there |
| Browser console errors? | `Ctrl+Shift+J` (Firefox `Ctrl+Shift+K`). The widget logs its chosen API URL as `[Widget] ... mode - API URL:`; a missing line means the script never ran, most likely a CSP block. There is no `widget.js` to 404, everything is inline in `widget.html` |
| Are you on a page that hides the widget? | Some BookStack admin pages strip custom HTML |
| Did you save Customisation **and** clear browser cache? | `Ctrl+Shift+R` / `Cmd+Shift+R` |

### "The widget opens but every message fails"

```bash
docker compose --env-file .env -f docker/docker-compose.yml logs chatbot --tail 50
```

Look for:

- `Denied <ip> (not in ALLOWED_VPN_IPS)` → your client IP is not on the allow-list. Add it to `ALLOWED_VPN_IPS` and recreate the container (`docker compose --env-file .env -f docker/docker-compose.yml up -d chatbot`; a plain `restart` keeps the old environment). If `<ip>` is your reverse proxy's address for every visitor, set `TRUSTED_PROXY_HOPS=1`.
- `ALLOWED_VPN_IPS is set but contains no valid CIDRs - denying all requests` → a typo in the list. Every request is refused until it parses.
- `Azure OpenAI not configured and Ollama fallback is disabled` → no provider in `.env`; the widget answers "no AI service is currently available". Set `AZURE_OPENAI_API_KEY` and `AZURE_OPENAI_ENDPOINT`, or `ENABLE_OLLAMA_FALLBACK=true`.
- `Rate limit exceeded for IP` → you hit `RATE_LIMIT_PER_MINUTE`. Wait 60 s or raise the limit.
- The widget shows `Network error` and the browser console a failed request → the page's origin cannot reach `/chat/api/widget`. In production the widget posts to BookStack's own origin, so the reverse proxy must route `/chat/api/` to the chatbot (`docker/nginx-example.conf`).

### "Widget answers but doesn't cite the wiki"

Three common causes:

1. **The index is empty.** The startup log says so (`The BookStack index is empty`).
   `python resync.py --dry-run` inside the chatbot container shows what it holds;
   `--full-resync` fills it.
2. **Webhooks are not configured**, or they are blocked: look for
   `Processing BookStack event:` lines in the chatbot log when you edit a page, and for
   `Denied` lines from the BookStack container's address. See
   [BOOKSTACK_WEBHOOKS.md](BOOKSTACK_WEBHOOKS.md).
3. **The index drifted.** If it cites pages that are gone, or misses pages that exist,
   rebuild it with `python resync.py --full-resync` inside the chatbot container. See
   [BOOKSTACK_WEBHOOKS.md](BOOKSTACK_WEBHOOKS.md).

## BookStack

### "BookStack shows the magnifying-glass icon and refuses to start"

This is BookStack's "I can't reach my database" screen.

```bash
docker compose --env-file .env -f docker/docker-compose.yml logs bookstack_db
```

Common fixes:

- `MYSQL_ROOT_PASSWORD` or `BOOKSTACK_DB_PASSWORD` mismatch between `.env` and a previous run that wrote to the volume. Either fix `.env` to match, or `docker compose down -v` (destroys data) and start fresh.
- The `mariadb_data` volume is on a full disk. `df -h` to check.

### "BookStack first-run setup-wizard never finishes"

The default `linuxserver/bookstack` image runs `php artisan migrate` on first boot. On slow disks (e.g. SD cards) this can time out.

```bash
docker compose --env-file .env -f docker/docker-compose.yml restart bookstack
# Wait 60 seconds, then refresh the browser.
```

### "API token says invalid"

- Tokens are case-sensitive. Re-copy them.
- Make sure you copied **both** the ID and the secret (they look similar).
- Token expired? Check expiry in BookStack: Settings → Users → (the token's user) → API Tokens.

## Chatbot Backend

### "`chatbot` is unhealthy, or answers every request with an error"

```bash
docker compose --env-file .env -f docker/docker-compose.yml logs chatbot --tail 100
```

Typical causes:

- A missing env var will **not** stop it. `SECRET_KEY` falls back to a built-in literal and `ALLOWED_VPN_IPS` falls back to allowing everything, both silently; look for the startup warnings rather than a crash.
- Database file permissions: the log says `Schema setup failed for /app/data/chatbot.db: attempt to write a readonly database` (the database file exists, as after an upgrade) or `… unable to open database file` (there is no file yet), and `/health` answers `503` with `"status": "unhealthy"`, so `docker compose ps` shows the container as unhealthy. The container runs as `1000:1000`. The image's `/app/data` belongs to that user since v0.3.0, so a fresh `chatbot_data` volume is writable; a volume created by an older image stays root-owned. Fix it once with `docker compose --env-file .env -f docker/docker-compose.yml run --rm --user root chatbot chown -R 1000:1000 /app/data`, then `docker compose --env-file .env -f docker/docker-compose.yml restart chatbot`: the database is set up only when the app starts, and `up -d` leaves a running container alone when its configuration has not changed. Do not run `kb_admin.py` as root against the volume's files: the `-wal` and `-shm` files it creates would be root-owned and lock the container out again.
- Out of memory. Raise `deploy.resources.limits.memory` for the `chatbot` service in `docker/docker-compose.yml`; it is 4 GB by default.

### "SQLite database is locked"

This happens if you run the admin CLI on the host while the container is also writing.

```bash
# Stop the container, then run the CLI, then start it again
docker compose --env-file .env -f docker/docker-compose.yml stop chatbot
python3 scripts/kb_admin.py bulk reindex --force
docker compose --env-file .env -f docker/docker-compose.yml start chatbot
```

For ad-hoc reads (`documents list`, `index status`, `maintenance health-check`) the lock
is usually not a problem and the container can keep running. The CLI needs a reachable
`DATABASE_PATH`; see [KB_ADMIN_CLI.md](KB_ADMIN_CLI.md).

## LLM Providers

### "Azure OpenAI returns 401 Unauthorized"

- `AZURE_OPENAI_API_KEY` is wrong, expired, or revoked. Check Azure Portal → your OpenAI resource → Keys and Endpoint.
- `AZURE_OPENAI_ENDPOINT` is passed to the Azure SDK unchanged as `azure_endpoint`; give it the resource URL in the form the Azure Portal shows, `https://my-resource.openai.azure.com/`.

### "Azure OpenAI returns 404 Not Found"

- `AZURE_OPENAI_DEPLOYMENT_NAME` doesn't match the deployment you created. It's the deployment name, not the model name.

### "Azure OpenAI returns 429 Too Many Requests"

You're hitting the rate limit. Either upgrade the Azure tier or reduce traffic:

```ini
RATE_LIMIT_PER_MINUTE=5         # cap user-side too
```

### "Ollama doesn't respond"

- Is it actually running? `curl http://localhost:11434/api/tags`
- Is `OLLAMA_BASE_URL` correct? From inside the chatbot container, `host.docker.internal` resolves to the host. From the host shell, `localhost` works.
- Is `ENABLE_OLLAMA_FALLBACK=true` set?
- Is the model pulled? The log says `Model <name> not found in Ollama` otherwise. `ollama pull mistral`, or set `OLLAMA_MODEL` to one you have.

## Performance

### "Queries take >5 seconds"

| Likely cause | Verify | Fix |
|---|---|---|
| Slow LLM provider | `response_time_ms` in the widget API response | Switch model (e.g. `gpt-4o-mini` instead of `gpt-4`) |
| Large prompt | `Widget LLM request: … context chars` in the log | Lower `PAGE_CONTEXT_CHARS` or `MAX_CONTEXT_DOCS` (see [CONFIGURATION.md](CONFIGURATION.md)) |
| Cold SQLite cache | First query after restart | Warms up after a few queries |
| Slow disk | `iostat -x 1` | Move `chatbot_data` volume to SSD |

### "A full resync or a large book stops with errors, and the log shows `429`"

BookStack limits each API user to 180 requests per minute by default
(`API_REQUESTS_PER_MIN`), and the chatbot reads one request per book, chapter and page.
A book with more items than that, synced by a webhook, or a full resync of a larger wiki
runs into the limit: the webhook job's retries (after 3, 6 and 12 s) end before the
minute is over, and a resync that hit errors does not prune. Raise the limit on the
`bookstack` service, for example `API_REQUESTS_PER_MIN=1000` under `environment:` in
`docker/docker-compose.yml`, and run `resync.py --full-resync` again.

### "Index rebuild is very slow"

`bulk reindex` runs every document through chunking and indexing in one thread, and
`--batch-size` only groups the work, it does not parallelise it. How long that takes
depends on document size and disk; measure one batch before scheduling the rest, and
run large rebuilds outside working hours because the writer lock is held throughout.

## Last Resort

If you've tried everything and the stack is broken in inscrutable ways:

```bash
# Save your wiki content first. The password is expanded inside the container
# (single quotes), where the compose file has set MYSQL_PASSWORD.
docker compose --env-file .env -f docker/docker-compose.yml exec -T bookstack_db \
  sh -c 'mariadb-dump -u bookstack -p"$MYSQL_PASSWORD" bookstackapp' > bookstack-backup.sql

# Do not go on unless the dump holds your content
grep -c 'INSERT INTO' bookstack-backup.sql

# Now nuke and reboot
docker compose --env-file .env -f docker/docker-compose.yml down -v
docker compose --env-file .env -f docker/docker-compose.yml up -d

# Once "ps" shows bookstack healthy, load the dump over the fresh database
docker compose --env-file .env -f docker/docker-compose.yml exec -T bookstack_db \
  sh -c 'mariadb -u bookstack -p"$MYSQL_PASSWORD" bookstackapp' < bookstack-backup.sql

# The chatbot's index went with its volume: rebuild it
docker compose --env-file .env -f docker/docker-compose.yml exec chatbot python resync.py --full-resync
```

The dump brings back everything BookStack keeps in its database: users and passwords,
roles, API tokens (so the ones in `.env` work again), webhooks, the custom head with the
widget, and all content. Keep `BOOKSTACK_APP_KEY` in `.env` unchanged, or BookStack cannot
decrypt what it encrypted with it. Do not dump as `root`: in the MariaDB image `root` signs
in from inside the container without a password, so `-u root -p"$MYSQL_ROOT_PASSWORD"` is
refused and leaves an empty file.

`down -v` deletes all three volumes, and the dump covers only one of them:

- `bookstack_data` holds BookStack's uploaded images and attachments.
- `chatbot_data` holds the chatbot's database and the documents uploaded with
  `kb_admin.py`. The BookStack index is rebuilt by the resync above; uploaded documents
  are not, and need to be uploaded again unless you copied them out.

Copy out whatever of those you need before `down -v`.

If the issue persists with a fresh stack, open a GitHub Issue with the output of:

```bash
docker compose --env-file .env -f docker/docker-compose.yml ps
docker compose --env-file .env -f docker/docker-compose.yml logs --tail 200 > debug.log
```

and attach `debug.log` (after redacting any secrets that may have leaked into it).
