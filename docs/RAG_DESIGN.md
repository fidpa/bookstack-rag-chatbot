# RAG Design

Deep dive into how the chatbot retrieves and answers. If you want to tune quality, this is the file.

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
    │   Multi-strategy FTS5 search │   per strategy, against both
    │   1. Title / tags             │   bookstack_chunks_fts and
    │   2. Exact phrase             │   kb_chunks_fts
    │   3. Keyword OR               │
    │   4. Keyword AND              │
    │   5. Proximity                │
    │   6. Chunk-level              │
    │   7. Fuzzy (fallback)         │
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

## Chunking Strategy

Wiki pages and uploaded documents are split into overlapping chunks before indexing. The strategy is sentence-aware with a sliding window:

| Parameter | Default | Where |
|---|---|---|
| Target chunk size | 800 words | `chatbot/bookstack/chunking.py` (`BookStackChunkingService.DEFAULTS`) |
| Overlap | 150 words (~19 %) | same |
| Sentence boundary detection | regex split on `.!?` followed by whitespace | same |
| Min chunk size | 80 words (smaller chunks merge with the next) | same |

Sentence-awareness matters because BM25 ranks token matches but humans read sentences. Splitting mid-sentence produces chunks where the most relevant token has lost its context.

Tuning notes:

- **Larger chunks** (e.g. 1 200 words) help when answers span multiple paragraphs, but they dilute BM25 scores and may exceed your LLM's context budget after concatenation.
- **Smaller chunks** (e.g. 400 words) increase precision but require more chunks in the prompt for the same effective context.

## FTS5 Configuration

SQLite FTS5 is created with content-table linkage and default tokeniser
(`unicode61`, accent-folding off):

```sql
CREATE VIRTUAL TABLE bookstack_chunks_fts USING fts5(
    title, chunk_text, content_type,
    content = bookstack_chunks,
    content_rowid = id
);
```

The default `unicode61` tokeniser handles ASCII and the common European
Unicode range. There is no stemming (no `porter`) and no accent folding
beyond the default — `über` will not match `uber` out of the box. If your
corpus needs either, add the relevant tokeniser options to the
`CREATE VIRTUAL TABLE` and reindex.

The `kb_chunks_fts` table is created the same way.

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
a strong signal of relevance — without requiring score normalisation
across strategies with different BM25 distributions.

The top results are then handed straight to the LLM as system context.

## Prompt Assembly

The final prompt looks like:

```
<SYSTEM>
You are an internal knowledge assistant for the bookstack-rag-chatbot demo.
Answer only from the provided sources. If the sources don't contain the answer,
say so explicitly. Cite the source URI in brackets after each claim.

<SOURCES>
[1] https://wiki.example.com/books/acme-knowledge-base/page/employee-handbook
    Acme runs a flexible-hours model with a small mandatory overlap window.
    Core hours: 10:00 to 15:00 local time. ...

[2] https://wiki.example.com/books/acme-knowledge-base/page/vacation-policy
    Acme believes that rested people make better decisions. ...

<USER>
What are Acme's core working hours?
```

The exact template lives in `chatbot/chat/context_builder.py` and is easy to customise.

## When This Breaks

| Symptom | Likely cause | Fix |
|---|---|---|
| Chatbot says "I don't know" for content that exists | Webhook didn't fire, or BookStack page is in `draft` state | Edit the page in BookStack; webhook fires on update |
| Off-topic answers, ignores sources | BM25 is matching weak signals across many strategies | Reduce chunk size, or narrow the system prompt |
| Hallucinated facts | System prompt didn't override the LLM's training | Make prompt stricter: "Answer ONLY from sources. Refuse otherwise." |
| Very slow responses (>5 s) | LLM provider is rate-limited or far away | Switch provider, or pick a smaller deployment |
| Out-of-memory at chunking time | Very large uploaded PDF | Pre-split the PDF, or raise `chatbot` memory limit in `docker-compose.yml` |

## Alternative Architectures Considered

| Approach | Why we didn't pick it |
|---|---|
| Pure vector search (embed all chunks, cosine similarity) | Higher infra cost, marginal quality gain on single-language internal docs |
| Hybrid (FTS5 + embeddings) | Complexity not justified at this corpus size |
| RAG over a vector DB only | Requires an embeddings pipeline + vector DB; doesn't add precision over multi-strategy FTS5 for our case |
| Fine-tuning an LLM on the wiki | Costs grow with every wiki update; RAG stays in sync automatically |
| Long-context prompting (stuff the whole wiki in the prompt) | Doesn't scale beyond ~50 pages |

If your corpus is multilingual or your queries are semantic-heavy (e.g. "find me policies similar to X"), embeddings start to pay off. Swap in a `pgvector`-backed `KnowledgeBaseService` and keep the rest of the pipeline.
