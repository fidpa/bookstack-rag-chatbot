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
| Knowledge base | Uploaded documents (`pdf`, `docx`, `txt`, `md`) | `chatbot.db` SQLite (`kb_*` tables), files in `knowledge_base/` next to it |
| Rate-limit counters | Per-IP request timestamps | In-memory in the Flask process, shared by its waitress threads, lost on restart |
| Chat sessions | The last 20 messages per conversation | In-memory in the Flask process for 30 minutes; the visitor's `sessionStorage` holds only the server-issued session id. No transcript is written anywhere |

The chatbot's SQLite database has two parallel sets of tables:

- `bookstack_content`, `bookstack_chunks`, `bookstack_fts`, `bookstack_chunks_fts`: mirrors BookStack content via webhooks. Created and, for installations made by older versions, replaced by `ensure_bookstack_schema()` at startup.
- `kb_documents`, `kb_chunks`, `kb_chunks_fts`, `kb_tags`: uploaded documents managed by the admin CLI. Created by `ensure_kb_schema()` at startup and by the CLI on first use.

At query time both indexes are searched in parallel using a multi-strategy FTS5 pipeline (title match, exact phrase, AND/OR keyword sets, proximity, chunk-level, fuzzy fallback). The result sets are fused with a score bonus per matching strategy, and the top candidates are handed to the LLM as context for the final answer.

## Why SQLite (and not Postgres / pgvector / Pinecone)

SQLite FTS5 was chosen deliberately. The trade-offs:

| Property | SQLite FTS5 | Postgres + pgvector | Pinecone / cloud vector DB |
|---|---|---|---|
| Operational complexity | One file, no service | Separate Postgres instance | External service, monthly cost |
| Latency (~10k docs, estimated) | <10 ms | ~30-80 ms | 50-200 ms + network |
| Quality on single-language internal docs | Competitive via multi-strategy fusion | Better for semantic queries | Best for multilingual / fuzzy queries |
| Multi-tenant | Hard | Easy | Easy |
| Multi-writer | No (single-writer lock) | Yes | Yes |
| Backup | Copy one file | `pg_dump` | Vendor-specific |

For a single-tenant internal wiki, SQLite + FTS5 + multi-strategy fusion is the simplest thing that works. The ~10 000-document figure is an estimate from FTS5's behaviour, not a measured ceiling; the deployment these numbers come from indexes about 150 pages.

**There is no storage abstraction to swap.** `chatbot/documents/knowledge_base/services/` splits the work into four classes (`StorageService`, `IndexingService`, `SearchService`, `ContextService`), which keeps the SQL in a small number of files, but none of them sits behind an interface and each writes FTS5 SQL directly. Moving to Postgres means rewriting those four, not implementing a base class. `LLMProvider` is the only abstraction in the codebase today; a `KnowledgeBaseService` counterpart would have to be introduced first, and that is the real cost of the swap.

## The LLM Factory

The `chatbot/llm/` module exposes a single interface, `LLMProvider`, with implementations for Azure OpenAI and Ollama.

```python
class LLMProvider(ABC):
    model: str = ""

    def __init__(self, name: str): ...

    @abstractmethod
    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str: ...
        # raises LLMError with a message safe to show to a visitor

    @abstractmethod
    def is_available(self) -> bool: ...
```

`get_llm_provider()` in `factory.py` chooses per request, Azure first, then Ollama
when `ENABLE_OLLAMA_FALLBACK=true`; each provider is built once per process so its
HTTP connections are reused. Switching providers is one env-var change and a container
restart.

There is no separate LLM reranking step today. The only LLM call is the final answer-generation `chat()`. If you want a true reranker, build it on top of the `LLMProvider` interface and insert it in `ContextService.build_knowledge_context()` (`chatbot/documents/knowledge_base/services/context.py`), between the hybrid search and `ChunkSelectionStrategy.build_context()`.

## Widget-Only Architecture

The chatbot has no UI of its own. There is no login, no user database, and no admin web interface. This is deliberate:

- BookStack already owns user identity. We trust whatever IP / session has been allowed past BookStack and the reverse proxy.
- One fewer login screen for users.
- One fewer system to harden against authentication bugs.

The flip side: this only works behind something that does authenticate. What the chatbot
itself enforces is an IP allow-list and a per-IP rate limit, and the allow-list allows
everything when `ALLOWED_VPN_IPS` is empty, which is how `.env.example` ships. A
public-internet deployment needs an auth proxy in front (nginx with OIDC, for example).

## Webhook-Driven Sync

The chatbot listens on `/webhook/bookstack` for 13 events:

- `page_create`, `page_update`, `page_delete`, `page_move`, `page_restore`
- `chapter_create`, `chapter_update`, `chapter_delete`, `chapter_move`
- `book_create`, `book_update`, `book_delete`, `book_sort`

Bookshelf events are not among them: a bookshelf holds no content of its own, so there is nothing to index (see [BOOKSTACK_WEBHOOKS.md](BOOKSTACK_WEBHOOKS.md)).

When BookStack fires a webhook, the chatbot fetches the affected content via the BookStack API and updates its FTS5 index. There is no scheduled cron job; the index converges with BookStack on every edit, in the time one API fetch plus a re-chunk takes.

All three delete events remove content, chapters and books by the `book_id` and
`chapter_id` columns the index records for every page. Where webhooks were missed
entirely, `chatbot/resync.py --full-resync` walks the API and prunes what BookStack no
longer reports. Both are written up in [BOOKSTACK_WEBHOOKS.md](BOOKSTACK_WEBHOOKS.md).

This depends on BookStack reaching the chatbot's `/webhook/bookstack` endpoint. Inside the stack they share `bookstack-network`, so the Docker-internal hostname is enough.

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
   │          │             │ ≤3 docs × 3 excerpts        │
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

The retrieval step returns at most three documents and at most three chunks each,
capped at 3000 words in total (`ContextService.MAX_CONTEXT_DOCS` and
`ChunkSelectionStrategy.build_context`).

Typical end-to-end latency, Azure OpenAI `gpt-4o-mini`, 150-page wiki, single user:
1.5 to 2.5 seconds, median 1.8. The dominant cost is the LLM call; FTS5 retrieval is
under 10 ms on that corpus.

## Where to Modify What

| You want to change… | …edit |
|---|---|
| Which LLM is used | `.env` (`AZURE_OPENAI_*`, `ENABLE_OLLAMA_FALLBACK`) |
| Add a new LLM provider | `chatbot/llm/providers/` (implement `LLMProvider`) and register in `chatbot/llm/factory.py` |
| Chunk size / overlap | `DEFAULTS` in `chatbot/bookstack/chunking.py` for wiki content and in `chatbot/documents/knowledge_base/services/chunking.py` for uploaded docs; the algorithm is `chatbot/utils/text_chunking.py` |
| Prompt template | `chatbot/chat/widget_service.py` (`DEFAULT_SYSTEM_PROMPT`, or override it with `CHATBOT_SYSTEM_PROMPT`) |
| Search terms, stopwords, synonyms | `chatbot/documents/knowledge_base/services/query_processor/` (`constants.py`, `preprocessor.py`) |
| How retrieved sources are rendered | `chatbot/documents/knowledge_base/services/strategies/chunk_strategy.py` |
| How much of the current page travels along | `ChatContextBuilder.PAGE_CONTEXT_CHARS` in `chatbot/chat/context_builder.py` |
| Rate-limit / IP allow-list | `.env` (`ALLOWED_VPN_IPS`, `RATE_LIMIT_PER_MINUTE`); enforcement is in `chatbot/utils/rate_limiter.py` |
| Repair a drifted index | `chatbot/resync.py` (`--dry-run`, `--full-resync`, `--no-prune`) |
| Widget look | `bookstack-integration/widget.html`. Colours, position and labels are literals in the file; there is no config object (see [WIDGET_INTEGRATION.md](WIDGET_INTEGRATION.md)) |
| Replace SQLite with Postgres+pgvector | Rewrite the four services in `chatbot/documents/knowledge_base/services/`. No interface exists to implement against; extracting one is step zero |
