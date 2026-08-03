# Architecture

## Components

### React frontend

- persistent conversation sidebar;
- source mode selector: Auto, Documents, General;
- multi-file upload and deletion;
- evidence citations and web-source cards;
- chat history stored in browser local storage.

### FastAPI backend

- typed request and response contracts with Pydantic;
- document ingestion and persistent evidence repository;
- local dense retrieval using `BAAI/bge-small-en-v1.5`;
- query intent, follow-up context, and source routing;
- grounded generation with explicit abstention;
- optional OpenAI-compatible chat and Tavily web search.

### Local persistence

```text
backend/data/uploads/   original uploaded files (Git ignored)
backend/data/index/     serialized evidence index (Git ignored)
browser localStorage    conversation history
```

## Trust boundaries

- The frontend never receives provider keys.
- Uploaded file names are sanitized and content-addressed.
- File extensions, sizes, and content are validated before indexing.
- Contact information is redacted before embedding.
- Generated citations can reference only retrieved evidence IDs.
- Auto mode requires a document-topic anchor before using document evidence.
- Live results expose their original URLs and are not treated as permanent.

## Main modules

| Module | Responsibility |
| --- | --- |
| `document_ingestion.py` | validation, extraction, chunking, persistence |
| `dense_retriever.py` | local semantic embedding and similarity search |
| `entity_guard.py` | blocks unsupported exact attributes and entities |
| `conversation_context.py` | resolves elliptical follow-up questions |
| `assistant_router.py` | selects documents, general chat, or guidance |
| `grounded_generator.py` | intent-shaped evidence-only answers |
| `general_knowledge.py` | hosted or local conversational generation |
| `web_search.py` | compact Tavily search with typed web sources |
| `query_service.py` | end-to-end orchestration and response contract |

## Current tradeoffs

The vector index is rebuilt in memory after uploads or deletions. This is
appropriate for a portfolio-scale corpus and keeps the implementation easy to
inspect. A production deployment would use a persistent vector database,
background ingestion jobs, authentication, rate limiting, and server-side chat
storage.
