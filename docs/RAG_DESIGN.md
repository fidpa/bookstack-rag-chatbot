# RAG Design

How the chatbot gets from a question to an answer, and which knobs change the result.
Everything below describes the path a widget request actually takes.

## Pipeline Overview

```
            query string
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
    │                               │   with a +50% bonus per
    │                               │   additional strategy that
    │                               │   matched the same document
    └──────────┬───────────────────┘
               ▼
    ┌──────────────────────────────┐
    │   Context builder             │   top candidates + current
    │                               │   BookStack page context
    └──────────┬───────────────────┘
               ▼
    ┌──────────────────────────────┐
    │   LLM completion              │   answer + cited source URIs
    └──────────┬───────────────────┘
               ▼
      JSON response
```

There is no separate LLM reranking step. The only LLM call is the final
answer generation, which sees the fused top candidates as system context.

Four of the seven strategies are conditional, in
`HybridSearchService._execute_multi_strategy_search`
(`chatbot/documents/knowledge_base/services/hybrid_search/core.py`):

- **Exact phrase** runs only with two or more keywords, over the first three
  must-have terms.
- **Keyword AND** runs only with two or more must-have terms.
- **Proximity** runs only with two or more keywords and an intent other than
  `GENERAL`, over the first two keywords at `distance=10`.
- **Fuzzy** runs only when everything above produced fewer than five results in
  total. It is a fallback, not a parallel path.

The BookStack tables are searched by two further calls, `search_bookstack_content`
and `search_bookstack_chunks`. They have no bucket of their own: their results are
appended to `KEYWORD_OR` and `CHUNK_BASED`, so a wiki page and an uploaded document
compete inside the same strategy for the fusion bonus.

## Chunking Strategy

Wiki pages and uploaded documents are split into overlapping chunks before indexing. The strategy is sentence-aware with a sliding window:

| Parameter | Default | Where |
|---|---|---|
| Target chunk size | 800 words | `chatbot/bookstack/chunking.py` (`BookStackChunkingService.DEFAULTS`) |
| Overlap | 150 words (~19 %) | same |
| Sentence boundary detection | `_split_into_sentences`: `.!?` before whitespace and an uppercase letter (`A-ZÄÖÜ`), `.!?` before a newline, a blank line as a paragraph break, or `.!?` at the end of the text | same |
| Min chunk size | 80 words (smaller chunks merge with the next) | same |

Sentence-awareness matters because BM25 ranks token matches but humans read sentences. Splitting mid-sentence produces chunks where the most relevant token has lost its context.

Tuning notes:

- **Larger chunks** (e.g. 1 200 words) help when answers span multiple paragraphs, but they dilute BM25 scores and may exceed your LLM's context budget after concatenation.
- **Smaller chunks** (e.g. 400 words) increase precision but require more chunks in the prompt for the same effective context.

## FTS5 Configuration

Three external-content FTS5 tables, all on the default tokeniser (`unicode61`,
accent-folding off). `ContentSyncService._init_db` creates the two BookStack ones and
keeps them current with triggers:

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

The default `unicode61` tokeniser handles ASCII and the common European
Unicode range. There is no stemming (no `porter`) and no accent folding
beyond the default: `über` will not match `uber` out of the box. If your
corpus needs either, add the relevant tokeniser options to the
`CREATE VIRTUAL TABLE` and reindex.

`scripts/init_kb_schema.py` creates the knowledge-base table, which indexes a single
column rather than three:

```sql
CREATE VIRTUAL TABLE kb_chunks_fts USING fts5(
    chunk_text,
    content='kb_chunks', content_rowid='id'
);
```

A title match on an uploaded document therefore comes from the `kb_documents` row, not
from the FTS index; on a wiki page it comes from the index.

## Score Fusion

Each FTS5 strategy returns its own ranked result set. `ResultFusion`
(`chatbot/documents/knowledge_base/services/hybrid_search/fusion.py`)
combines them with a per-strategy sum plus a bonus:

```
score(d) = ( Σ score_i(d) ) × (1 + 0.5 × strategies_matched(d))
            i
```

A document that matches three strategies (e.g. exact phrase + AND + title)
ends up with a 2.5× multiplier over a document that only matched one. The
multiplier captures the intuition that hitting multiple retrieval paths is
a strong signal of relevance, without requiring score normalisation
across strategies with different BM25 distributions.

The top results are then handed straight to the LLM as system context.

## Prompt Assembly

Two system messages and the conversation reach the provider, assembled in
`chatbot/chat/widget_service.py`:

1. **The instruction prompt**, the `default_system_prompt` literal, or whatever
   `CHATBOT_SYSTEM_PROMPT` replaces it with. It names the two sources, asks for brief
   citations, tells the model to say so when the sources do not answer, and to reply in
   the user's language.
2. **The retrieved context**, as
   `f"Relevant context from knowledge base:\n{combined_context}"`.
3. **The last ten messages** of the conversation. When the widget sent page context, the
   current user message is extended with `[Current page context: ...]`.

`combined_context` is built by `ChunkSelectionStrategy.build_context`
(`…/services/strategies/chunk_strategy.py`) and looks like this, with German section
labels left over from the original deployment:

```
## Relevante Informationen aus der Wissensbasis:

### Dokument 1: Employee Handbook
[Auszug 1]
Acme runs a flexible-hours model with a small mandatory overlap window.
Core hours: 10:00 to 15:00 local time. ...

### Dokument 2: Vacation and Leave Policy
[Auszug 1]
...
```

At most three documents (`ContextService.MAX_CONTEXT_DOCS`), at most three chunks each,
and at most 3000 tokens in total; when the budget runs out the builder appends
`[Weitere relevante Informationen vorhanden, aber Context-Limit erreicht]` and stops.

There are **no source URLs in the context**. The prompt asks the model to cite briefly,
and the model does that from the document titles it can see; nothing hands it a link,
and nothing checks that a citation appeared.

### How wiki content reaches the context

Two routes, and they are separate on purpose:

- **The page the visitor is on.** The widget sends it as `page_content` in
  `bookstack_context`, and `ChatContextBuilder` puts the first 2000 characters into the
  context block under a `BookStack Page:` heading.
- **Retrieved pages.** `search_bookstack_content` and `search_bookstack_chunks` query
  the `bookstack_*` tables inside the hybrid search, and `ResultConverters` turns each
  hit into a virtual `KnowledgeDocument` carrying the FTS5 snippet as its text.
  `ChunkSelectionStrategy.build_context` renders those from the snippet, since a wiki
  hit has no `kb_chunks` rows to join against.

The two BookStack searches find the same page under different synthetic ids, so
`build_context` groups them on the underlying BookStack item rather than on the
document id; otherwise one page would take two of the three context slots. Excerpts a
document already carries verbatim are dropped, and the `<mark>` tags FTS5 puts around
matched terms are stripped before the text goes into the prompt.

Chunks from both sources are ordered on one convention, smaller is better: FTS5 `rank`
for knowledge-base chunks, `-relevance_score` for wiki hits.

## When This Breaks

| Symptom | Likely cause | Fix |
|---|---|---|
| Chatbot says "I don't know" for content that exists | Webhook didn't fire, or BookStack page is in `draft` state | Edit the page in BookStack; webhook fires on update |
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
