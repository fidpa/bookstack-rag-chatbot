# Setup

A full local installation, from `git clone` to the chatbot's first answer, in about 10 minutes.

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Docker | 20.10+ | With Compose v2 |
| Python | 3.11+ | For `samples/load-samples.py` (needs `requests`) and the admin CLI (needs `pip install -r chatbot/requirements.txt`), both of which run on the host, not in the container |
| `curl` | any | For the health checks below |

Optional but recommended:

- An Azure OpenAI deployment or a local Ollama instance.

## 1. Clone

```bash
git clone https://github.com/fidpa/bookstack-rag-chatbot.git
cd bookstack-rag-chatbot
```

## 2. Configure environment

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
AZURE_OPENAI_ENDPOINT=       # required alongside the key; Azure is skipped without it
ALLOWED_VPN_IPS=             # e.g. 192.168.0.0/16,172.16.0.0/12; empty allows every source IP
```

`ALLOWED_VPN_IPS` has to cover two kinds of caller: the browsers of your readers, and
the BookStack container, which delivers webhooks from the Docker network
(`172.16.0.0/12` covers Docker's default bridge ranges). Leaving the Docker range out
blocks every webhook with a 403.

Two of these fail quietly rather than loudly if you skip them. An unset `SECRET_KEY`
falls back to a literal published in this repository, and an empty `ALLOWED_VPN_IPS`
lets any source reach the chatbot. Both are fine on a laptop and neither is fine on a
network; [SECURITY.md](SECURITY.md) has the rest of the list.

`BOOKSTACK_TOKEN_ID` and `BOOKSTACK_TOKEN_SECRET` stay empty for now; you fill them in after BookStack has booted.

## 3. Boot the stack

```bash
docker compose -f docker/docker-compose.yml up -d
```

This starts three containers: `bookstack`, `bookstack_db`, `chatbot`. The first boot takes ~30 seconds while BookStack runs database migrations.

Verify everything is healthy:

```bash
docker compose -f docker/docker-compose.yml ps
# All services should show "(healthy)" after ~1 minute
```

## 4. Create the BookStack admin account

Open `http://localhost:6875` and sign in with BookStack's default admin account,
`admin@admin.com` with the password `password`. Change both immediately.

## 5. Generate a BookStack API token

In BookStack:

1. Click your avatar (top-right) → **My Account**.
2. Scroll to **API Tokens** → **Create Token**.
3. Set a name (e.g. `chatbot`) and an expiry date.
4. Copy the **Token ID** and the **Token Secret**. The secret is shown **only once**.

Put both into `.env`:

```ini
BOOKSTACK_TOKEN_ID=...
BOOKSTACK_TOKEN_SECRET=...
```

Restart the chatbot so it picks up the new tokens:

```bash
docker compose -f docker/docker-compose.yml restart chatbot
```

## 6. Set up the webhook

Webhooks keep the index in step with every edit. In BookStack, go to **Settings →
Webhooks → Create Webhook**, point it at `http://chatbot:8888/webhook/bookstack` and
select the 13 events listed in [BOOKSTACK_WEBHOOKS.md](BOOKSTACK_WEBHOOKS.md).

## 7. Embed the chat widget

In BookStack:

1. Go to **Settings → Customisation → Custom HTML head content**.
2. Paste the entire content of `bookstack-integration/widget.html`.
3. Save.

Reload any wiki page. The chat bubble appears in the lower-right corner.

## 8. Load and index the demo content

Make sure your shell has the BookStack credentials exported:

```bash
pip install requests
set -a; . ./.env; set +a
python3 samples/load-samples.py
```

The loader talks to the BookStack API over `BOOKSTACK_EXTERNAL_URL` with the token you
just created. It refuses to create duplicate pages, so a second run exits non-zero
rather than doubling the content; `--delete` removes the book again.

This creates one BookStack book called *Acme Inc. Knowledge Base* with five sample
pages. With the webhook from step 6 in place, the chatbot indexes each page as it is
created. Content that existed before the webhook, or a stack without one, needs a
full sync:

```bash
docker compose -f docker/docker-compose.yml exec chatbot python resync.py --full-resync
```

`python resync.py --dry-run` in the same place shows what the index holds.

## 9. Ask your first question

Open any page in BookStack. Click the chat bubble. Try:

> What are Acme's core working hours?

You should get an answer with its sources named. On the production deployment behind
this repository the median is 1.8 s end to end with Azure OpenAI `gpt-4o-mini`; a cold
start after boot is slower.

## Where to next

- [CONFIGURATION.md](CONFIGURATION.md): make sense of every `.env` variable
- [WIDGET_INTEGRATION.md](WIDGET_INTEGRATION.md): what is configurable in the widget, and what has to be edited in the file
- [KB_ADMIN_CLI.md](KB_ADMIN_CLI.md): upload your own documents (PDF, DOCX, Markdown, text)
- [SECURITY.md](SECURITY.md): read before exposing this beyond `localhost`
