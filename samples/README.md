# Sample Knowledge Base — Acme Inc.

This directory contains a small, **fictional** corporate knowledge base for a made-up company called *Acme Inc.* It exists so that you can boot the stack and immediately ask the RAG chatbot real questions.

All content is original and released into the **public domain (CC0)**. Companies, products, people, and policies described here are entirely fictional — any resemblance to real organisations is coincidental.

## Contents

| File | Topic | Suggested test questions |
|---|---|---|
| `acme-employee-handbook.md` | Working hours, benefits, IT policy basics | "What are Acme's core working hours?" |
| `acme-it-onboarding.md` | New-joiner IT setup | "How do I request a laptop at Acme?" |
| `acme-vacation-policy.md` | Vacation rules, public holidays, sick leave | "How many vacation days does Acme give?" |
| `acme-product-faq.md` | Product Q&A for *Acme Widget v3* | "Does the Acme Widget support webhooks?" |
| `acme-meeting-rooms.md` | Conference room booking rules | "How do I book the Helsinki room?" |

## Loading the samples

After the stack is running and BookStack has been initialised (admin account created at `http://localhost:6875`), generate an API token (My Account → API Tokens → Create Token), put the credentials into `.env`, then load them into your shell and run the loader (it reads the process environment, not the file):

```bash
set -a; . ./.env; set +a
python3 samples/load-samples.py
```

The script creates one BookStack book called *Acme Inc. Knowledge Base* and uploads each Markdown file as a page. With the webhook set up ([docs/BOOKSTACK_WEBHOOKS.md](../docs/BOOKSTACK_WEBHOOKS.md)), the chatbot indexes each page as it is created. Without one, index them in one go:

```bash
docker compose -f docker/docker-compose.yml exec chatbot python resync.py --full-resync
```

## Removing the samples

```bash
python3 samples/load-samples.py --delete
```

This removes the book and all its pages from BookStack. The deletion itself fires `book_delete`, which removes them from the chatbot's index; without a webhook, `resync.py --full-resync` prunes them.
