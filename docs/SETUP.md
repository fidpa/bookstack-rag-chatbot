# Setup

This guide walks you through a full local installation — from `git clone` to asking the chatbot its first question — in about 10 minutes.

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Docker | 20.10+ | With Compose v2 |
| Python | 3.11+ | Only for running `samples/load-samples.py` and the admin CLI on the host |
| `curl` | any | For the health checks below |

Optional but recommended:

- An Azure OpenAI deployment or a local Ollama instance.

## 1 — Clone

```bash
git clone https://github.com/fidpa/bookstack-rag-chatbot.git
cd bookstack-rag-chatbot
```

## 2 — Configure environment

```bash
cp .env.example .env
```

Open `.env` in your editor and fill in **at minimum**:

```ini
SECRET_KEY=                  # openssl rand -hex 32
BOOKSTACK_DB_PASSWORD=       # any strong password
MYSQL_ROOT_PASSWORD=         # any strong password
BOOKSTACK_APP_KEY=           # see comment in .env.example for how to generate
AZURE_OPENAI_API_KEY=        # OR configure Ollama (see ENABLE_OLLAMA_FALLBACK)
```

`BOOKSTACK_TOKEN_ID` / `BOOKSTACK_TOKEN_SECRET` stay empty for now — you'll fill them in after BookStack has booted.

## 3 — Boot the stack

```bash
docker compose -f docker/docker-compose.yml up -d
```

This starts three containers: `bookstack`, `bookstack_db`, `chatbot`. The first boot takes ~30 seconds while BookStack runs database migrations.

Verify everything is healthy:

```bash
docker compose -f docker/docker-compose.yml ps
# All services should show "(healthy)" after ~1 minute
```

## 4 — Create the BookStack admin account

Open `http://localhost:6875`. On first boot, BookStack prints the default admin credentials in its container log:

```bash
docker compose -f docker/docker-compose.yml logs bookstack | grep -A2 "Default Admin"
```

Sign in and immediately change the password.

## 5 — Generate a BookStack API token

In BookStack:

1. Click your avatar (top-right) → **My Account**.
2. Scroll to **API Tokens** → **Create Token**.
3. Set a name (e.g. `chatbot`) and an expiry date.
4. Copy the **Token ID** and the **Token Secret** — the secret is shown **only once**.

Put both into `.env`:

```ini
BOOKSTACK_TOKEN_ID=...
BOOKSTACK_TOKEN_SECRET=...
```

Restart the chatbot so it picks up the new tokens:

```bash
docker compose -f docker/docker-compose.yml restart chatbot
```

## 6 — Embed the chat widget

In BookStack:

1. Go to **Settings → Customisation → Custom HTML head content**.
2. Paste the entire content of `bookstack-integration/widget.html`.
3. Save.

Reload any wiki page — you should see a chat bubble in the lower-right.

## 7 — Load the demo content

Make sure your shell has the BookStack credentials exported:

```bash
set -a; . ./.env; set +a
python3 samples/load-samples.py
```

This creates one BookStack book called *Acme Inc. Knowledge Base* with five sample pages. The chatbot's webhook listener will index them within seconds.

## 8 — Ask your first question

Open any page in BookStack. Click the chat bubble. Try:

> What are Acme's core working hours?

You should get a sourced answer within 1–3 seconds.

## Where to next

- [CONFIGURATION.md](CONFIGURATION.md) — make sense of every `.env` variable
- [WIDGET_INTEGRATION.md](WIDGET_INTEGRATION.md) — customise the widget colour, position, and start message
- [KB_ADMIN_CLI.md](KB_ADMIN_CLI.md) — upload your own documents (PDF, DOCX, MD)
- [SECURITY.md](SECURITY.md) — before exposing this beyond `localhost`
