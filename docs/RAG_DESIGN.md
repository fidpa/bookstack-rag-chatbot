# RAG Design

How the chatbot gets from a question to an answer, and which knobs change the result.
Everything below describes the path a widget request actually takes.

## Pipeline Overview

```
            the visitor's question
                 │
                 ▼
    ┌──────────────────────────────┐
    │   Query analyser              │   intent, keywords, entities,
    │                               │   must-have terms
    └──────────┬───────────────────┘
               ▼
    ┌──────────────────────────────┐
    │   Multi-strategy FTS5 search │   nine calls into seven
    │   1. Title / tags             │   strategy buckets, against
    │   2. Exact phrase      (cond) │   kb_chunks_fts and the
    │   3. Keyword OR               │   bookstack_* tables
    │   4. Keyword AND       (cond) │
    │   5. Proximity         (cond) │
    │   6. Chunk-level              │
    │   7. Fuzzy         (fallback) │
    └──────────┬───────────────────┘
               ▼
    ┌──────────────────────────────┐
    │   Score fusion                │   sum of per-strategy scores,
    │                               │   +50% per distinct strategy
    │                               │   that found the document
    └──────────┬───────────────────┘
               ▼
    ┌──────────────────────────────┐
    │   Context builder             │   current page + excerpts of
    │                               │   the top three documents
    └──────────┬───────────────────┘
               ▼
    ┌──────────────────────────────┐
    │   LLM completion              │   instruction prompt, context,
    │                               │   last ten turns, question
    └──────────┬───────────────────┘
               ▼
      JSON response
```

The search runs on the question alone. The page the visitor is on goes into the
prompt as context (see below), but not into the search query: mixed in, its text
would decide which keywords the analyser picks.

There is no separate LLM reranking step. The only LLM call is the final
answer generation, which sees the fused top candidates as system context.

Four of the seven strategies are conditional, in
`HybridSearchService._execute_multi_strategy_search`
(`chatbot/documents/knowledge_base/services/hybrid_search/core.py`):

- **Exact phrase** runs only with two or more keywords, over the first three keywords
  in the order the question names them ("vacation policy").
- **Keyword AND** runs only with two or more must-have terms.
- **Proximity** runs only with two or more keywords and an intent other than
  `GENERAL`, over the first two keywords at `distance=10`.
- **Fuzzy** runs only when everything above produced fewer than five results in
  total. It is a fallback, not a parallel path.

The BookStack tables are searched by two further calls, `search_bookstack_content`
and `search_bookstack_chunks`. They have no bucket of their own: their results are
appended to `KEYWORD_OR` and `CHUNK_BASED`, so a wiki page and an uploaded document
compete inside the same strategy for the fusion bonus.

### Query analysis and FTS5 syntax

Keywords are the question's words of three or more characters (letters of any script
and digits, so `404` counts) minus German and English stopwords
(`query_processor/constants.py`). Every term reaches FTS5 as a quoted string, built by
`query_processor/preprocessor.py`. That matters: bare words are FTS5 syntax, and a
question with an upper-case `NOT`, `AND` or `NEAR`, a hyphen or a stray quote would
otherwise become an operator or a syntax error. A question with no searchable word at
all (`"?!"`) skips the search instead of matching anything.

`SYNONYMS` in the same constants file expands keywords into extra search variants.
It ships empty; useful synonyms depend on the wiki's vocabulary.

## Chunking Strategy

Wiki pages and uploaded documents are split into overlapping chunks before indexing,
by one implementation, `TextChunker` in `chatbot/utils/text_chunking.py`:

| Parameter | Wiki pages | Uploads | Where |
|---|---|---|---|
| Target chunk size | 800 words | 1000 words | `BookStackChunkingService.DEFAULTS` / `ChunkingService.DEFAULTS` |
| Overlap | 150 words (~19 %) | 200 words | same |
| Min chunk size | 80 words | 100 words | same; smaller chunks merge into the next |

The text is first split into units: sentences (`.!?` before whitespace and a capital
letter or digit) and lines. Lines matter because list items, table cells and headings
carry no sentence punctuation; `clean_html_content()` in `sync_service.py` therefore
turns block elements (`<p>`, `<li>`, `<tr>`, headings, `<br>`) into line breaks before
stripping the tags. Units are packed into chunks up to the target size, and the last
units of a chunk, up to the overlap, start the next one. A single unit longer than a
whole chunk is cut into overlap-sized word windows, so no chunk exceeds the target.

Sentence-awareness matters because BM25 ranks token matches but humans read sentences. Splitting mid-sentence produces chunks where the most relevant token has lost its context.

Tuning notes:

- **Larger chunks** (e.g. 1 200 words) help when answers span multiple paragraphs, but they dilute BM25 scores and may exceed your LLM's context budget after concatenation.
- **Smaller chunks** (e.g. 400 words) increase precision but require more chunks in the prompt for the same effective context.

Changing either configuration needs a rebuild of the affected index; see
[CONFIGURATION.md](CONFIGURATION.md#tuning-recipes).

## FTS5 Configuration

Three external-content FTS5 tables, all on the default tokeniser `unicode61`, which
folds diacritics: `uber` matches `über`. There is no stemming (no `porter`); add the
tokeniser option to the `CREATE VIRTUAL TABLE` and rebuild if your corpus needs it.

`BOOKSTACK_SCHEMA` in `chatbot/bookstack/sync_service.py` creates the two BookStack
tables:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS bookstack_fts USING fts5(
    title, content, tags,
    content=bookstack_content, content_rowid=id
);

CREATE VIRTUAL TABLE IF NOT EXISTS bookstack_chunks_fts USING fts5(
    title, chunk_text, content_type,
    content=bookstack_chunks, content_rowid=id
);
```

`KB_SCHEMA` in `chatbot/documents/knowledge_base/schema.py` creates the
knowledge-base table, which indexes a single column rather than three:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS kb_chunks_fts USING fts5(
    chunk_text,
    content='kb_chunks', content_rowid='id'
);
```

A title match on an uploaded document therefore comes from the `kb_documents` row, not
from the FTS index; on a wiki page it comes from the index.

Triggers keep the three indexes in step with their content tables. Because the
content is external, a trigger cannot simply `DELETE` or `UPDATE` the FTS row: FTS5
would read the terms to remove from the content table, where they are already gone or
replaced. The triggers use FTS5's `'delete'` command with the old values instead, and
BookStack items are written with `INSERT ... ON CONFLICT DO UPDATE` so the update
trigger fires. Items are keyed by `(bookstack_id, type)`, since BookStack numbers
books, chapters and pages separately.

## Score Fusion

Each strategy scores its hits as its weight times the hit's bm25 relevance relative to
the best hit of the same search, so the best hit gets the full weight and weaker ones
proportionally less (`strategies.py`, `relative_relevance`):

| Strategy | Weight |
|---|---|
| Title / tags | 3.0 |
| Exact phrase | 2.5 |
| Keyword AND | 2.0 |
| Proximity | 1.8 |
| Keyword OR | 1.5 |
| Chunk-level | 1.3 |
| Fuzzy | 1.0 |

`ResultFusion` (`chatbot/documents/knowledge_base/services/hybrid_search/fusion.py`)
then combines them per document:

```
score(d) = ( Σ score_i(d) ) × (1 + 0.5 × distinct_strategies(d))
            i
```

A document found by three strategies gets a multiplier of 2.5, one found by a single
strategy 1.5, so the first is weighted 1.67 times as strongly before the scores are
compared. The multiplier captures the intuition that hitting multiple retrieval paths
is a strong signal of relevance. Each strategy counts once per document, even when
the BookStack searches add a second hit to the same bucket.

A wiki item's page-level hit and its chunk hits share one id, so they merge into one
document here and occupy one of the three context slots.

## Prompt Assembly

The provider receives, assembled in `chatbot/chat/widget_service.py`:

1. **The instruction prompt**, `DEFAULT_SYSTEM_PROMPT`, or `CHATBOT_SYSTEM_PROMPT` when
   that is set and not empty. It names the two sources, asks for brief citations, tells
   the model to say so when the sources do not answer, and to reply in the user's
   language.
2. **The context**, as one system message
   `f"Relevant context from knowledge base:\n{combined_context}"`.
3. **The last ten messages** of the conversation (five exchanges). The session lives in
   memory for 30 minutes; a turn that failed is not stored.
4. **The question**, unchanged.

`combined_context` starts with the page the visitor is on, when the widget sent it:
up to 20,000 characters (`ChatContextBuilder.PAGE_CONTEXT_CHARS`) under a
`BookStack Page:` heading with its URL. The retrieved excerpts follow, built by
`ChunkSelectionStrategy.build_context` (`…/services/strategies/chunk_strategy.py`):

```
## Relevant information from the knowledge base:

### Document 1: Employee Handbook
[Excerpt 1]
Acme runs a flexible-hours model with a small mandatory overlap window.
Core hours: 10:00 to 15:00 local time. ...

### Document 2: Vacation and Leave Policy
[Excerpt 1]
...
```

At most three documents (`ContextService.MAX_CONTEXT_DOCS`), at most three excerpts
each, and at most 3000 words in total; when the budget runs out the builder appends
`[More relevant information exists but the context limit was reached]` and stops.
When no document contributes an excerpt, the block is left out entirely.

Retrieved documents carry their title but no URL. The prompt asks the model to cite
briefly, and it does that from the titles; nothing checks that a citation appeared.

### How wiki content reaches the context

- **The page the visitor is on.** The widget sends it as `page_content` in
  `bookstack_context`, and `ChatContextBuilder` puts it into the context block, once.
- **Retrieved pages.** `search_bookstack_chunks` returns the full text of each page's
  best-matching chunks; `ResultConverters` carries them on the virtual
  `KnowledgeDocument` it builds per wiki hit, and `build_context` uses up to three of
  them. A page found only as a whole, without a matching chunk, contributes its FTS5
  snippet instead.

## When This Breaks

| Symptom | Likely cause | Fix |
|---|---|---|
| Chatbot says "I don't know" for content that exists | The index is empty or stale: webhooks not set up, or a page still in `draft` | `docker compose exec chatbot python resync.py --dry-run` shows what the index holds; `--full-resync` fills it |
| Off-topic answers, ignores sources | BM25 is matching weak signals across many strategies | Reduce chunk size, or narrow the system prompt |
| Hallucinated facts | System prompt didn't override the LLM's training | Make prompt stricter: "Answer ONLY from sources. Refuse otherwise." |
| Very slow responses (>5 s) | LLM provider is rate-limited or far away | Switch provider, or pick a smaller deployment |
| Out-of-memory at chunking time | Very large uploaded PDF | Pre-split the PDF, or raise `deploy.resources.limits.memory` for `chatbot` in `docker/docker-compose.yml` |

## Alternative Architectures Considered

| Approach | Why we didn't pick it |
|---|---|
| Pure vector search (embed all chunks, cosine similarity) | Higher infra cost, marginal quality gain on single-language internal docs |
| Hybrid (FTS5 + embeddings) | Complexity not justified at this corpus size |
| RAG over a vector DB only | Requires an embeddings pipeline + vector DB; doesn't add precision over multi-strategy FTS5 for our case |
| Fine-tuning an LLM on the wiki | Costs grow with every wiki update; RAG stays in sync automatically |
| Long-context prompting (stuff the whole wiki in the prompt) | Doesn't scale beyond ~50 pages |

If your corpus is multilingual or your queries are semantic-heavy (e.g. "find me policies similar to X"), embeddings start to pay off. That is not a swap today: the retrieval code writes FTS5 SQL directly in `chatbot/documents/knowledge_base/services/`, with no backend interface behind it. A `pgvector` variant means extracting that interface first and then reimplementing storage, indexing and search against it. The chunking, fusion and prompt-building stages above are backend-agnostic and would survive the move.
