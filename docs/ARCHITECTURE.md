# Architecture

This document explains the design choices behind the chatbot and where the seams are if you want to evolve it.

## The Three Services

```
┌───────────────────────────────────────────────────────┐
│              bookstack-network (bridge)                │
│                                                       │
│  ┌───────────────┐    ┌──────────────┐                │
│  │   bookstack   │───►│ bookstack_db │                │
│  │ (port 6875)   │    │  (MariaDB)   │                │
│  └──────┬────────┘    └──────────────┘                │
│         │ webhooks (over network)                     │
│         ▼                                             │
│  ┌────────────────────────────────────────────────┐   │
│  │   chatbot  (port 8888, Flask)                  │   │
│  │   ├─ HTTP /chat/api/widget → widget             │   │
│  │   ├─ HTTP /webhook/bookstack → sync           │   │
│  │   └─ outbound HTTPS → LLM provider             │   │
│  │                                                │   │
│  │   data volume: chatbot.db (SQLite FTS5)        │   │
│  └────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────┘
```

**Why three services and not two?**
BookStack and its database (MariaDB) are separate by convention; we leave them as-is. The chatbot is its own service because:

1. We don't want to fork BookStack.
2. We want to scale / restart the chatbot independently.
3. The chatbot has very different runtime needs (Python, outbound HTTP to LLMs) than BookStack (PHP, mostly inbound).

## Data Stores

| Store | What | Where |
|---|---|---|
| BookStack content | Pages, books, chapters | MariaDB (managed by BookStack) |
| Chatbot index | Mirror of BookStack content as FTS5 rows | `chatbot.db` SQLite |
| Knowledge base | User-uploaded documents (PDF/DOCX/MD) | `chatbot.db` SQLite (`kb_*` tables) |
| Chat sessions | Per-IP rate-limit counters | In-memory only (lost on restart, deliberately) |

The chatbot's SQLite database has two parallel sets of tables:

- `bookstack_content`, `bookstack_chunks`, `bookstack_chunks_fts` — mirrors BookStack content via webhooks.
- `kb_documents`, `kb_chunks`, `kb_chunks_fts` — uploaded documents managed by the admin CLI.

At query time both indexes are searched in parallel using a multi-strategy FTS5 pipeline (title match, exact phrase, AND/OR keyword sets, proximity, chunk-level, fuzzy fallback). The result sets are fused with a score bonus per matching strategy, and the top candidates are handed to the LLM as context for the final answer.

## Why SQLite (and not Postgres / pgvector / Pinecone)

SQLite FTS5 was chosen deliberately. The trade-offs:

| Property | SQLite FTS5 | Postgres + pgvector | Pinecone / cloud vector DB |
|---|---|---|---|
| Operational complexity | One file, no service | Separate Postgres instance | External service, monthly cost |
| Latency on ~10k docs | <10 ms | ~30–80 ms | 50–200 ms + network |
| Quality on single-language internal docs | Competitive via multi-strategy fusion | Better for semantic queries | Best for multilingual / fuzzy queries |
| Multi-tenant | Hard | Easy | Easy |
| Multi-writer | No (single-writer lock) | Yes | Yes |
| Backup | Copy one file | `pg_dump` | Vendor-specific |

For a single-tenant internal wiki up to ~10 000 documents, SQLite + FTS5 + multi-strategy fusion is the simplest thing that works. The `documents/knowledge_base/services/` layer is abstracted as a `KnowledgeBaseService` interface — drop in a `PostgresKnowledgeBaseService` when you outgrow SQLite.

## The LLM Factory

The `chatbot/llm/` module exposes a single interface, `LLMProvider`, with implementations for Azure OpenAI and Ollama.

```python
class LLMProvider(ABC):
    @abstractmethod
    def chat(self, messages: list[dict], **kwargs) -> str: ...

    @abstractmethod
    def complete(self, prompt: str, **kwargs) -> str: ...

    @abstractmethod
    def is_available(self) -> bool: ...
```

`factory.py` chooses an implementation at startup based on env vars, with explicit preference order. Switching providers is one env-var change and a container restart.

There is no separate LLM reranking step today — the only LLM call is the final answer-generation `chat()`. If you want a true reranker, build it on top of the `LLMProvider` interface and insert it between `ResultFusion.fuse_and_rank_results()` and `ChatContextBuilder.build_combined_context()` in `chatbot/chat/widget_service.py`.

## Widget-Only Architecture

The chatbot has no UI of its own. There is no login, no user database, and no admin web interface. This is deliberate:

- BookStack already owns user identity. We trust whatever IP / session has been allowed past BookStack and the reverse proxy.
- One fewer login screen for users.
- One fewer system to harden against authentication bugs.

The flip side: this only works behind something that does authenticate. A public-internet deployment needs an auth proxy (e.g. nginx + OIDC).

## Webhook-Driven Sync

The chatbot listens on `/webhook/bookstack` for 16 events:

- `page_create`, `page_update`, `page_delete`, `page_move`, `page_restore`
- `chapter_create`, `chapter_update`, `chapter_delete`, `chapter_move`
- `book_create`, `book_update`, `book_delete`, `book_sort`
- `bookshelf_create`, `bookshelf_update`, `bookshelf_delete` (see [BOOKSTACK_WEBHOOKS.md](BOOKSTACK_WEBHOOKS.md))

When BookStack fires a webhook, the chatbot fetches the affected page(s) via the BookStack API and updates its FTS5 index. There is no scheduled cron job; the index converges with BookStack on every edit, typically within 1–2 seconds.

This depends on BookStack reaching the chatbot's `/webhook/bookstack` endpoint — they share a Docker network, so this is trivially possible inside the stack.

## Sequence: A Query, End to End

```
Visitor   widget.html    chatbot         SQLite FTS5     LLM
   │          │             │                │            │
   │ click    │             │                │            │
   ├─────────►│             │                │            │
   │  POST /chat/api/widget  │                │            │
   │          ├────────────►│                │            │
   │          │             │ IP allow-list  │            │
   │          │             │ + rate limit   │            │
   │          │             │                │            │
   │          │             │ FTS5 query     │            │
   │          │             ├───────────────►│            │
   │          │             │ top-10 chunks  │            │
   │          │             │◄───────────────┤            │
   │          │             │                │            │
   │          │             │ answer with sources         │
   │          │             ├────────────────────────────►│
   │          │             │ chat response                │
   │          │             │◄────────────────────────────┤
   │          │ 200 OK      │                │            │
   │          │◄────────────┤                │            │
   │ render   │             │                │            │
   │◄─────────┤             │                │            │
```

Typical end-to-end latency, Azure OpenAI gpt-4o-mini, 150-page wiki, single user: 1.5–2.5 seconds. The dominant cost is the LLM call; FTS5 retrieval is under 10 ms.

## Where to Modify What

| You want to change… | …edit |
|---|---|
| Which LLM is used | `.env` (`AZURE_OPENAI_*`, `ENABLE_OLLAMA_FALLBACK`) |
| Add a new LLM provider | `chatbot/llm/providers/` (implement `LLMProvider`) and register in `chatbot/llm/factory.py` |
| Chunk size / overlap | `chatbot/bookstack/chunking.py` for wiki content; `chatbot/documents/knowledge_base/services/chunking.py` for uploaded docs |
| Prompt template | `chatbot/chat/context_builder.py` |
| Rate-limit / IP allow-list | `.env` (`ALLOWED_VPN_IPS`, `RATE_LIMIT_PER_MINUTE`) — enforcement is in `chatbot/utils/rate_limiter.py` |
| Widget look | `bookstack-integration/widget.html` (vanilla JS/CSS, no build step) |
| Replace SQLite with Postgres+pgvector | Implement `KnowledgeBaseService` for Postgres in `chatbot/documents/knowledge_base/services/` |
