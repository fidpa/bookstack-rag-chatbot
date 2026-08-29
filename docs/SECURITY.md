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

Both run before any LLM call. Three things are worth knowing about the allow-list
before you rely on it:

1. **An empty `ALLOWED_VPN_IPS` allows every source.** The decorator logs one warning
   at startup and then passes everything through. `.env.example` ships it empty.
2. **`IP_ACCESS_CONTROL=false` disables it entirely**, for every endpoint at once.
3. **`X-Forwarded-For` is trusted as sent.** `_client_ip()` returns the header's first
   entry when present, so a client that can reach the chatbot directly can name its own
   source IP. This is only safe behind a proxy that strips the inbound header.

Not behind the allow-list: `/health`, `/` (a redirect to BookStack), the static route,
and `GET|POST /webhook/bookstack/test`, which answers unauthenticated with the list of
accepted webhook events. `/debug` lists the URL map but returns 403 unless
`app.debug` is on.

## Rendering of model output

`addMessage()` in `bookstack-integration/widget.html` assigns answers with
`contentDiv.textContent = content`, never `innerHTML`. Markup in an answer, whether the
model produced it or a wiki page smuggled it in, is displayed as text and not parsed,
so an injected page cannot turn into script running in the reader's BookStack session.
The chat panel's own chrome is built with `innerHTML` from string literals in the file,
with no data interpolated into it.

## In Scope (we try to defend against this)

- Widget XSS through model or wiki content, by the `textContent` rule above
- IP allow-list bypass, within the limits above
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

## Logging

`chatbot/chat/widget_service.py` logs the assembled prompt and every message at `INFO`,
truncated to 100 and 150 characters:

```python
logger.info(f"Widget LLM Request - System Prompt: {widget_system_prompt[:100]}...")
logger.info(f"Widget LLM Message {i}: {msg['role']} - {content_preview}")
```

User questions and retrieved wiki content land in the container log at the default
`LOG_LEVEL=INFO`. Anyone who can read `docker compose logs` can read what people asked.
Raise `LOG_LEVEL` to `WARNING` where that matters, and redact before attaching logs to
an issue.

## Hardening Checklist

Before exposing this beyond `localhost`, work through the list.

### Network layer

- [ ] Terminate TLS at a reverse proxy (nginx, Caddy, Traefik). The chatbot speaks plain HTTP.
- [ ] Restrict `/chat/api/` and `/webhook/` to your LAN or VPN at the proxy, not only at the chatbot.
- [ ] If the proxy is reachable from the public internet, strip inbound `X-Forwarded-For` before setting your own.
- [ ] Put a real CIDR list in `ALLOWED_VPN_IPS`. Empty means allow all, and `0.0.0.0/0` means the same thing with more typing.

### Application layer

- [ ] **Set `SECRET_KEY`.** `chatbot/config.py` falls back to the literal
      `"chatbot-dev-secret-change-in-production"` when the variable is unset, and the
      app starts without complaint. Flask session cookies are then signed with a key
      that is published in this repository.
- [ ] Rotate `SECRET_KEY`, `BOOKSTACK_TOKEN_SECRET` and `MYSQL_ROOT_PASSWORD` on a schedule.
- [ ] Keep `FLASK_DEBUG=false` and `FLASK_ENV=production`. The `.env.example` defaults are already correct.
- [ ] Keep `ENABLE_OLLAMA_FALLBACK=false` unless you run a hardened Ollama instance yourself.
- [ ] Keep `IP_ACCESS_CONTROL=true`.
- [ ] Pick a `RATE_LIMIT_PER_MINUTE` you have thought about. 30 suits an internal wiki.
- [ ] Leave `BOOKSTACK_WEBHOOK_SECRET` empty against stock BookStack. Setting it makes the endpoint demand a signature header that BookStack v25.07 does not send, and every delivery fails with 401.

### Container layer

The shipped `docker-compose.yml` already sets:

- `security_opt: no-new-privileges:true` on all three services
- Health checks on all three services
- CPU and memory limits on `chatbot` (2 vCPU / 4 GB, reserving 0.5 / 512 MB). BookStack and MariaDB run without limits.
- `user: "1000:1000"` on `chatbot`
- Pinned image tags (`linuxserver/bookstack:25.07`, `linuxserver/mariadb:11.5`)

You may want to add:

- [ ] `read_only: true` on `chatbot`, with `tmpfs` where Python needs to write (`/tmp`, `/app/flask_session`).
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
