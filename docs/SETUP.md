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

Every `docker compose` command in this guide is run from the repository root and
names the file explicitly: `docker compose --env-file .env -f docker/docker-compose.yml …`.
Compose reads `.env` from the directory of the compose file (`docker/`), not from
where you run it, so without `--env-file .env` all the values below stay empty (and
an empty `ALLOWED_VPN_IPS` allows every source).

Open `.env` in your editor and fill in **at minimum**:

```ini
SECRET_KEY=                  # openssl rand -hex 32
BOOKSTACK_DB_PASSWORD=       # any strong password
MYSQL_ROOT_PASSWORD=         # any strong password
BOOKSTACK_APP_KEY=           # see .env.example: docker run --rm --entrypoint /bin/bash lscr.io/linuxserver/bookstack:25.07.3 appkey
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
docker compose --env-file .env -f docker/docker-compose.yml up -d
```

This starts three containers: `bookstack`, `bookstack_db`, `chatbot`. The first boot takes ~30 seconds while BookStack runs database migrations.

Verify everything is healthy:

```bash
docker compose --env-file .env -f docker/docker-compose.yml ps
# All services should show "(healthy)" after ~1 minute
```

## 4. Create the BookStack admin account

Open `http://localhost:6875` and sign in with BookStack's default admin account,
`admin@admin.com` with the password `password`. Change both immediately.

## 5. Generate a BookStack API token

**Decide whose token this is before you create it.** The chatbot indexes everything the
token's user can see, and it answers every client that passes the allow-list from that index:
BookStack's role and page permissions are not applied per asker. A token from an
administrator therefore puts restricted books and pages into the answers for everyone.
Create a dedicated user instead:

- **Settings → Roles → Create New Role** (say `chatbot`): system permission *Access System API*,
  and only the *View* permissions for all books, chapters and pages (no create, edit or delete).
- **Settings → Users → Add New User** with only that role.

A page whose permissions exclude that role stays out of the index, and a full resync drops it
again if it was restricted after it had been indexed. The menu names are those of
BookStack 25.07; the token user's visibility is what counts, whatever the menus are called.

Still signed in as the administrator, create the token for that user:

1. **Settings → Users**, open the user you just created.
2. Under **API Tokens**, click **Create Token**.
3. Set a name (e.g. `chatbot`) and an expiry date.
4. Copy the **Token ID** and the **Token Secret**. The secret is shown **only once**.

(Your own tokens are under **My Account → Access & Security → API Tokens**.)

Put both into `.env`:

```ini
BOOKSTACK_TOKEN_ID=...
BOOKSTACK_TOKEN_SECRET=...
```

Recreate the chatbot so it picks up the new tokens:

```bash
docker compose --env-file .env -f docker/docker-compose.yml up -d chatbot
```

A plain `restart` does not do this: it restarts the container with the environment it
was created with, so the tokens would stay empty.

## 6. Set up the webhook

Webhooks keep the index in step with every edit: BookStack reports the change and the chatbot reads the item back a couple of seconds later. In BookStack, go to **Settings →
Webhooks → Create Webhook**, point it at `http://chatbot:8888/webhook/bookstack` and
select the 14 events listed in [BOOKSTACK_WEBHOOKS.md](BOOKSTACK_WEBHOOKS.md).

## 7. Embed the chat widget

In BookStack:

1. Go to **Settings → Customisation → Custom HTML head content**.
2. Paste the entire content of `bookstack-integration/widget.html`.
3. Save.

Reload any wiki page. The chat bubble appears in the lower-right corner.

## 8. Load and index the demo content

Give the loader the BookStack credentials from `.env` (in a subshell, so `.env` does not
end up exported in your own shell, where its values would win over later edits of `.env`
the next time you run Compose):

```bash
pip install requests
(set -a; . ./.env; set +a; python3 samples/load-samples.py)
```

The loader creates a book and pages, which the read-only token from step 5 may not do.
Give it an admin's token for this run: create one under **My Account → Access & Security →
API Tokens**, put it into `.env` as `SAMPLES_TOKEN_ID` and `SAMPLES_TOKEN_SECRET`, and delete
the token in BookStack once the samples are loaded. Without those two the loader falls back
to `BOOKSTACK_TOKEN_ID`/`BOOKSTACK_TOKEN_SECRET` and stops with a hint if BookStack refuses.
It talks to the BookStack API over `BOOKSTACK_EXTERNAL_URL`. It refuses to create duplicate
pages, so a second run exits non-zero rather than doubling the content; `--delete` removes
the book again.

This creates one BookStack book called *Acme Inc. Knowledge Base* with five sample
pages. With the webhook from step 6 in place, the chatbot indexes each page a few seconds
after it is created. Content that existed before the webhook, or a stack without one,
needs a full sync:

```bash
docker compose --env-file .env -f docker/docker-compose.yml exec chatbot python resync.py --full-resync
```

`python resync.py --dry-run` in the same place shows what the index holds.

## 9. Ask your first question

Open any page in BookStack. Click the chat bubble. Try:

> What are Acme's core working hours?

You should get an answer with its sources named. The deployment this repository was
extracted from reported a median of 1.8 s end to end with Azure OpenAI `gpt-4o-mini`
(not re-measured against this release); a cold start after boot is slower.

## Where to next

- [CONFIGURATION.md](CONFIGURATION.md): make sense of every `.env` variable
- [WIDGET_INTEGRATION.md](WIDGET_INTEGRATION.md): what is configurable in the widget, and what has to be edited in the file
- [KB_ADMIN_CLI.md](KB_ADMIN_CLI.md): upload your own documents (PDF, DOCX, Markdown, text)
- [SECURITY.md](SECURITY.md): read before exposing this beyond `localhost`
