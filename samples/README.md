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

After the stack is running and BookStack has been initialised (admin account created at `http://localhost:6875`), generate an API token (My Account → API Tokens → Create Token), put the credentials into `.env`, then run:

```bash
python3 samples/load-samples.py
```

The script creates one BookStack book called *Acme Inc. Knowledge Base* and uploads each Markdown file as a page. The chatbot's webhook listener will pick them up and index them into the RAG store within a few seconds.

## Removing the samples

```bash
python3 samples/load-samples.py --delete
```

This removes the book and all its pages from BookStack. The chatbot's index will be cleaned up on the next webhook event.
