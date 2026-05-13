# Security Policy

## Supported Versions

Only the latest minor release receives security fixes.

| Version | Supported |
|---------|-----------|
| 1.x     | ✅        |
| < 1.0   | ❌        |

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Instead, open a [GitHub Security Advisory](https://github.com/fidpa/bookstack-rag-chatbot/security/advisories/new) on this repository. Private disclosure lets us coordinate a fix and a release before the issue becomes public.

When reporting, please include:

- A description of the issue and its potential impact
- Steps to reproduce (proof-of-concept code if applicable)
- Affected version(s)
- Your suggested remediation (if you have one)

We aim to acknowledge reports within 72 hours and to release a fix or mitigation within 14 days for high-severity issues.

## Threat Model

This project is designed to run **inside a trusted network** (LAN, VPN, or behind a reverse proxy that handles TLS and authentication). The following attack surfaces are explicitly in scope:

| Surface | In scope |
|---|---|
| Widget XSS (BookStack-page injection) | ✅ |
| Prompt injection via document content | ✅ |
| IP allow-list bypass via reverse-proxy headers | ✅ |
| Rate-limit bypass | ✅ |
| BookStack API token theft via misconfiguration | ✅ |
| SQL injection in the admin CLI | ✅ |
| Container breakout from the chatbot backend | ✅ |
| Public, internet-exposed deployments without TLS or auth | ❌ (out of scope) |
| Compromise of the underlying host OS | ❌ |
| Compromise of the LLM provider (Azure/Anthropic/Ollama) | ❌ |

## Known Limitations

These are documented design trade-offs, not vulnerabilities:

- BookStack webhooks (as of v25.07) do not support HMAC signature validation — webhook authenticity is enforced via IP allow-list only.
- SQLite FTS5 is a single-writer database. For multi-instance deployments, swap the backend for PostgreSQL + `pgvector` (see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)).
- The Ollama fallback is **disabled by default** to prevent accidental fallback to a non-hardened local model.

## Hardening Recommendations

When deploying:

- Terminate TLS at a reverse proxy (nginx, Caddy, Traefik) — the chatbot backend speaks plain HTTP on the Docker network.
- Restrict `ALLOWED_VPN_IPS` to the narrowest CIDR that includes your users.
- Rotate `BOOKSTACK_TOKEN_SECRET` and `SECRET_KEY` quarterly.
- Mount the database volume read-only for any sidecar that does not need to write.
- Keep `ENABLE_OLLAMA_FALLBACK=false` unless you have a hardened Ollama instance.
