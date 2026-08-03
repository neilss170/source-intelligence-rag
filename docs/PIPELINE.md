# End-to-end pipeline

## 1. Ingestion

```text
Upload
  -> extension and size validation
  -> safe content-addressed filename
  -> format-specific extraction
  -> contact-detail redaction
  -> paragraph / row / record chunking
  -> evidence IDs + source provenance
  -> persistent JSON repository
  -> retriever cache invalidation
```

Every evidence unit retains a document ID, filename, page/record number, title,
and exact source text.

## 2. Query context

The request contains the current question, source scope, session ID, and up to
20 recent chat messages. Short elliptical follow-ups are expanded using the
last user topic. Complete questions remain unchanged.

## 3. Routing

```text
Explicit Documents -> RAG or empty-workspace guidance
Explicit General   -> general chat, with live search when needed
Auto               -> retrieve, validate topic anchor, then choose:
                      document answer / general chat / live search
```

Live search is triggered only by time-sensitive or link-oriented intent, such
as prices, availability, products, recommendations, news, websites, or “near
me”. This preserves API credits and reduces tokens.

## 4. Document retrieval

1. Route likely document section where applicable.
2. Embed the query with BGE-small.
3. Retrieve semantic candidates above the minimum score.
4. Apply strict entity and attribute guards.
5. Rerank candidates with a cross-encoder relevance model.
6. Select adaptive top-k based on question type.
7. Require lexical topic support before Auto mode uses document evidence.

## 5. Answer generation

The answer planner detects yes/no, where, when, who, list, fact, summary, and
explanation intent. Simple questions use the smallest sufficient evidence.
Summary and explanation requests may use multiple chunks.

An affirmative answer is allowed only when the requested subject occurs in the
selected evidence. Otherwise the system abstains.

## 6. Validation

The generator returns evidence IDs, not arbitrary citations. The API validates
that every cited ID was actually retrieved. Insufficient answers return no
citations and a groundedness score of zero.

## 7. General chat

An OpenAI-compatible provider is preferred. Without a key, the system uses a
small local model and refuses facts that it cannot verify. Recent chat messages
are included for conversational follow-ups.

## 8. Live search

Tavily basic search returns at most three results, a compact answer, short
snippets, and original URLs. Full raw pages are not sent to the model. Prices
and availability are labeled as changeable.

## 9. Evaluation

Tests cover extraction, chunking, retrieval, routing, conversation context,
answer intent, citation validation, no-answer behavior, live-search triggers,
and API contracts. Public RAG datasets remain evaluation inputs rather than
live user knowledge.
