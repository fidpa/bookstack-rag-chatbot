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

### "The widget opens but every message says 'Service unavailable'"

```bash
docker compose -f docker/docker-compose.yml logs chatbot --tail 50
```

Look for:

- `Denied <ip> (not in ALLOWED_VPN_IPS)` → your client IP is not on the allow-list. Add it, restart `chatbot`.
- `ALLOWED_VPN_IPS is set but contains no valid CIDRs - denying all requests` → a typo in the list. Every request is refused until it parses.
- `LLM provider not configured` → no provider key in `.env`. Set `AZURE_OPENAI_API_KEY` or `ENABLE_OLLAMA_FALLBACK=true`.
- `rate limit exceeded` → you hit `RATE_LIMIT_PER_MINUTE`. Wait 60 s or raise the limit.

### "Widget answers but doesn't cite the wiki"

Two common causes:

1. **The index is empty.** No content has reached it yet. Run `samples/load-samples.py`
   to prove the loop end to end, then look for `Processing BookStack event:` lines in the
   chatbot log when you edit a real page.
2. **Webhooks are not configured**, or they arrive and change nothing. The endpoint
   answers `processed` either way, so the log is the only witness. See
   [BOOKSTACK_WEBHOOKS.md](BOOKSTACK_WEBHOOKS.md).
3. **The index drifted.** If it cites pages that are gone, or misses pages that exist,
   rebuild it with `python resync.py --full-resync` inside the chatbot container. See
   [BOOKSTACK_WEBHOOKS.md](BOOKSTACK_WEBHOOKS.md).

## BookStack

### "BookStack shows the magnifying-glass icon and refuses to start"

This is BookStack's "I can't reach my database" screen.

```bash
docker compose -f docker/docker-compose.yml logs bookstack_db
```

Common fixes:

- `MYSQL_ROOT_PASSWORD` or `BOOKSTACK_DB_PASSWORD` mismatch between `.env` and a previous run that wrote to the volume. Either fix `.env` to match, or `docker compose down -v` (destroys data) and start fresh.
- The `mariadb_data` volume is on a full disk. `df -h` to check.

### "BookStack first-run setup-wizard never finishes"

The default `linuxserver/bookstack` image runs `php artisan migrate` on first boot. On slow disks (e.g. SD cards) this can time out.

```bash
docker compose -f docker/docker-compose.yml restart bookstack
# Wait 60 seconds, then refresh the browser.
```

### "API token says invalid"

- Tokens are case-sensitive. Re-copy them.
- Make sure you copied **both** the ID and the secret (they look similar).
- Token expired? Check expiry in BookStack: My Account → API Tokens.

## Chatbot Backend

### "Healthcheck failing, `chatbot` keeps restarting"

```bash
docker compose -f docker/docker-compose.yml logs chatbot --tail 100
```

Typical causes:

- A missing env var will **not** stop it. `SECRET_KEY` falls back to a built-in literal and `ALLOWED_VPN_IPS` falls back to allowing everything, both silently; look for the startup warnings rather than a crash.
- Database file permissions. The container runs as `1000:1000`; if you bind-mounted a host directory owned by root, fix the host permissions: `sudo chown -R 1000:1000 ./data`.
- Out of memory. Raise `deploy.resources.limits.memory` for the `chatbot` service in `docker/docker-compose.yml`; it is 4 GB by default.

### "SQLite database is locked"

This happens if you run the admin CLI on the host while the container is also writing.

```bash
# Stop the container, then run the CLI, then start it again
docker compose -f docker/docker-compose.yml stop chatbot
PYTHONPATH=chatbot python3 scripts/kb_admin.py bulk reindex --force
docker compose -f docker/docker-compose.yml start chatbot
```

For ad-hoc reads (`documents list`, `index status`, `maintenance health-check`) the lock
is usually not a problem and the container can keep running. The CLI needs `PYTHONPATH`
and a reachable `DATABASE_PATH`; see [KB_ADMIN_CLI.md](KB_ADMIN_CLI.md).

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

## Performance

### "Queries take >5 seconds"

| Likely cause | Verify | Fix |
|---|---|---|
| Slow LLM provider | Check chatbot logs for elapsed time per stage | Switch model (e.g. `gpt-4o-mini` instead of `gpt-4`) |
| Many candidate chunks in the prompt | Look at the assembled context size in the logs | Trim chunk size or shorten `ChatContextBuilder` output |
| Cold SQLite cache | First query after restart | Warms up after a few queries |
| Slow disk | `iostat -x 1` | Move `chatbot_data` volume to SSD |

### "Index rebuild is very slow"

`bulk reindex` runs every document through chunking and indexing in one thread, and
`--batch-size` only groups the work, it does not parallelise it. How long that takes
depends on document size and disk; measure one batch before scheduling the rest, and
run large rebuilds outside working hours because the writer lock is held throughout.

## Last Resort

If you've tried everything and the stack is broken in inscrutable ways:

```bash
# Save your wiki content first!
docker compose -f docker/docker-compose.yml exec bookstack_db \
  mysqldump -u root -p"$MYSQL_ROOT_PASSWORD" bookstackapp > bookstack-backup.sql

# Now nuke and reboot
docker compose -f docker/docker-compose.yml down -v
docker compose -f docker/docker-compose.yml up -d

# Restore BookStack (re-run setup, then restore DB)
```

If the issue persists with a fresh stack, open a GitHub Issue with the output of:

```bash
docker compose -f docker/docker-compose.yml ps
docker compose -f docker/docker-compose.yml logs --tail 200 > debug.log
```

and attach `debug.log` (after redacting any secrets that may have leaked into it).
