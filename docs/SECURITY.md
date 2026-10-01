# Security

The threat model, the hardening checklist, and the things this project does **not**
defend against. Every claim below is a statement about code in this repository; where
a defence is missing, it says so rather than describing an intention.

## What actually guards the endpoints

Two decorators, both in `chatbot/utils/rate_limiter.py`:

- `require_allowed_ip` matches the source IP against the CIDRs in `ALLOWED_VPN_IPS`.
  It is on `/chat/api/widget`, `/chat/api/echo` and `/webhook/bookstack`.
- `rate_limiter.ip_limit()` applies a sliding per-IP window, `RATE_LIMIT_PER_MINUTE`
  requests per 60 seconds, default 30. It is on `/chat/api/widget` only.

Both run before any LLM call. Neither limits what one request costs, so the widget API
refuses questions longer than 2,000 characters and bounds the page title and URL it takes
from the client (the page text is cut at 20,000 characters); keyword extraction used to be
quadratic in the length of the question, which made one long question enough to occupy a
waitress thread for seconds. Three things are worth knowing about the allow-list
before you rely on it:

1. **An empty `ALLOWED_VPN_IPS` allows every source.** The decorator logs one warning
   on the first guarded request and then passes everything through. `.env.example`
   ships it empty.
2. **`IP_ACCESS_CONTROL=false` disables it entirely**, for every endpoint at once.
3. **The address checked is the connecting one** unless `TRUSTED_PROXY_HOPS` is set.
   With the default `0`, `X-Forwarded-For` is ignored. Behind a reverse proxy every
   request then comes from the proxy's address, so set `TRUSTED_PROXY_HOPS=1`: werkzeug's
   `ProxyFix` takes the entry that proxy appended (the rightmost) and ignores what the
   client sent before it. That is only sound while port 8888 cannot be reached around
   the proxy (`CHATBOT_BIND` defaults to `127.0.0.1` for this reason); a client talking to it directly could otherwise send the header itself.
   Before v0.3.0 the leftmost entry was trusted, which any client controls.

The rate limiter keeps its request log in memory, shared by the waitress threads under
a lock, and forgets clients without requests in the last minute.

Not behind the allow-list: `/health` (status and version; `503` when the database setup
failed at startup), `/` (a redirect to
BookStack), `/chat/widget` (the standalone chat page, whose API calls are guarded),
`/favicon.ico`, the static route, and `GET|POST /webhook/bookstack/test`, which
answers unauthenticated with the list of accepted webhook events. `/debug` lists the
URL map but returns 403 unless `FLASK_DEBUG=true`.

Error responses carry a generic message; exception text stays in the log.

## BookStack permissions do not apply to answers

The chatbot has no identity for the person asking. It indexes what the BookStack API
token's user can see (the API applies that user's role and page permissions), and it
answers every client that passes the allow-list from that one index. Checked against
BookStack 25.07.3: a page restricted to the Admin role redirects an anonymous visitor to
the login page, while the chatbot, running with an administrator's token, indexed it and put
its text into the retrieved context for a request that carried no BookStack session at all.

So the token decides who may read what through the chatbot:

- Create it for a dedicated user whose role can only view content that everyone with
  chatbot access may read (see [SETUP.md](SETUP.md), step 5). Never use an administrator's.
- Restricting a page, chapter or book afterwards removes it from the index a few seconds
  later, through the `permissions_update` webhook (since v0.5.0; it has to be subscribed,
  see [BOOKSTACK_WEBHOOKS.md](BOOKSTACK_WEBHOOKS.md#changed-permissions)). Until the job has
  run, and whenever the webhook did not reach the chatbot or the job gave up (`Webhook job
  … gave up` in the log), the page stays answerable.
- Changes that BookStack reports without naming an item do not reach the index: editing a
  role, giving the token's user other roles, and *Copy permissions to books* on a shelf.
  Run `resync.py --full-resync` after those.
- A deployment that needs per-user answers needs a different design; the chatbot does not
  offer one.

## Rendering of model output

`addMessage()` in `bookstack-integration/widget.html`, and its counterpart in the
standalone page `chatbot/templates/chat/widget.html`, assign answers with
`contentDiv.textContent = content`, never `innerHTML`. Markup in an answer, whether the
model produced it or a wiki page smuggled it in, is displayed as text and not parsed,
so an injected page cannot turn into script running in the reader's BookStack session.
The chat panel's own chrome is built with `innerHTML` from string literals in the file,
with no data interpolated into it.

The standalone page accepts page context through `postMessage` only from the origin of
`BOOKSTACK_EXTERNAL_URL`; a page that frames it from elsewhere cannot feed text into
the prompt that way.

## In Scope (we try to defend against this)

- Widget XSS through model or wiki content, by the `textContent` rule above
- IP allow-list bypass, within the limits above
- A token that can see more than the chatbot's audience may read (see above): your responsibility when you create it
- Rate-limit exhaustion of the LLM budget
- BookStack API-token theft via misconfiguration
- SQL injection through the admin CLI
- Container breakout from the chatbot backend

## Out of Scope (we do not defend against this)

- Public, internet-exposed deployments without TLS, auth, or a hardened proxy in front
- Compromise of the underlying host OS
- Compromise of the LLM provider (Azure OpenAI or Ollama)
- Compromise of the BookStack instance itself
- Insider threats with legitimate write access to the wiki

## Prompt Injection: not mitigated today

The chatbot puts retrieved wiki content into a system message, verbatim:

```python
# chatbot/chat/widget_service.py
llm_messages.append({
    "role": "system",
    "content": f"Relevant context from knowledge base:\n{combined_context}",
})
```

There are no delimiters around the retrieved text, no instruction telling the model to
treat it as data rather than as instructions, and no check on the answer that comes
back. The default system prompt asks the model to cite its sources, but nothing rejects
an answer that cites none.

**A wiki page can therefore instruct the model.** Anyone who can edit a page, or get a
document into the knowledge base, can put text there that the model will read as part
of its own instructions. Treat write access to the wiki as equivalent to control over
the chatbot's answers, and restrict it accordingly. Hardening this is an open task:
delimiting the context block, adding an explicit data-not-instructions rule to the
prompt, and validating that answers cite a retrieved source would each raise the bar.

## Logging and stored data

The chatbot stores no chat transcripts: conversation history lives in memory for 30
minutes per session (at most 5000 sessions) and is gone on restart. Nothing about
visitors is written to the database.

The log is a different matter. At the default `LOG_LEVEL=INFO` the search logs the
keywords it extracted from each question (`Query analysis: ... Keywords=[...]`) and the
title of the page a visitor asked from. Anyone who can read `docker compose logs` can
reconstruct roughly what people asked. Set `LOG_LEVEL=WARNING` where that matters, and
redact before attaching logs to an issue.

## Hardening Checklist

Before exposing this beyond `localhost`, work through the list.

### Network layer

- [ ] Terminate TLS at a reverse proxy (nginx, Caddy, Traefik). The chatbot speaks plain HTTP.
- [ ] Restrict `/chat/api/` and `/webhook/` to your LAN or VPN at the proxy, not only at the chatbot.
- [ ] Behind a proxy, set `TRUSTED_PROXY_HOPS=1` and publish only the proxy, not port 8888 (the default `CHATBOT_BIND=127.0.0.1` keeps it on the host; do not widen it). `docker/nginx-example.conf` replaces `X-Forwarded-For` rather than appending to it.
- [ ] Put a real CIDR list in `ALLOWED_VPN_IPS`. Empty means allow all, and `0.0.0.0/0` means the same thing with more typing.

### Application layer

- [ ] **Set `SECRET_KEY`.** `chatbot/config.py` falls back to the literal
      `"chatbot-dev-secret-change-in-production"` when the variable is unset. Nothing
      is signed with it today, but anything added later would be signed with a key
      published in this repository.
- [ ] Rotate `SECRET_KEY`, `BOOKSTACK_TOKEN_SECRET` and `MYSQL_ROOT_PASSWORD` on a schedule.
- [ ] Keep `FLASK_DEBUG=false`. The `.env.example` default is already correct.
- [ ] Keep `ENABLE_OLLAMA_FALLBACK=false` unless you run a hardened Ollama instance yourself.
- [ ] Keep `IP_ACCESS_CONTROL=true`.
- [ ] Pick a `RATE_LIMIT_PER_MINUTE` you have thought about. 30 suits an internal wiki.
- [ ] Leave `BOOKSTACK_WEBHOOK_SECRET` empty against stock BookStack. Setting it makes the endpoint demand a signature header that BookStack v25.07 does not send, and every delivery fails with 401.

### Container layer

The shipped `docker-compose.yml` already sets:

- `security_opt: no-new-privileges:true` on all three services
- Health checks on all three services
- CPU and memory limits on `chatbot` (2 vCPU / 4 GB, reserving 0.5 / 512 MB). BookStack and MariaDB run without limits.
- `user: "1000:1000"` on `chatbot`; the image itself also runs as uid 1000 and owns `/app/data`
- Pinned image tags (`linuxserver/bookstack:25.07.3`, `linuxserver/mariadb:11.4.9`; a tag that does not exist fails at `docker compose up`, so check them with `docker manifest inspect` when you change them)

You may want to add:

- [ ] `read_only: true` on `chatbot`, with `tmpfs` on `/tmp`; the chatbot writes only to the `/app/data` volume.
- [ ] `cap_drop: [ALL]`.
- [ ] Resource limits on `bookstack` and `bookstack_db`.
- [ ] Rootless Docker or a user-namespace remap.

### Secrets

- [ ] Do not commit `.env`. The included `.gitignore` covers it.
- [ ] Prefer Docker secrets or an external secret manager over bare env vars in production.
- [ ] Make sure your CI runner does not log `.env` content.

## Reporting a Vulnerability

See the top-level [SECURITY.md](../SECURITY.md). Please do not open public GitHub issues
for security reports.
