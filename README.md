# Source Intelligence

A hybrid RAG chatbot that combines document-grounded question answering,
conversation memory, general chat, and optional live web search.

The project is designed as a graduate portfolio system: every document answer
is traceable to retrieved evidence, unsupported document questions abstain, and
current web results are shown with clickable sources.

## Features

- Upload PDF, DOCX, TXT, Markdown, CSV, JSON, and XLSX files.
- Remove documents and their indexed evidence.
- Local BGE embeddings with adaptive semantic retrieval.
- Cross-encoder reranking for final passage relevance.
- Intent-aware answers for yes/no, where, when, lists, facts, and explanations.
- Evidence validation and page/record citations.
- Automatic routing between documents, general chat, and live web search.
- Persistent ChatGPT-style conversations with follow-up context.
- Optional OpenAI-compatible chat provider.
- Optional Tavily live search using three compact results.
- Automated tests for parsing, retrieval, routing, grounding, and APIs.

## Architecture

```text
Question + recent chat history
              |
       context resolution
              |
       intent/source router
       /       |        \
 documents   general    live web
     |          |          |
 retrieval   chat LLM   Tavily Search
     |          |          |
 grounding     answer    source cards
       \         |         /
          typed API response
```

See [docs/PIPELINE.md](docs/PIPELINE.md) for the complete ingestion and query
pipelines and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for component
boundaries. The rejected learned-gating experiment and its held-out results are
documented in [docs/ANSWERABILITY_EXPERIMENT.md](docs/ANSWERABILITY_EXPERIMENT.md).

## Quick start

### Everything in Docker

```powershell
Copy-Item backend\.env.example backend\.env   # then add your CHAT_API_KEY
docker compose up --build
```

Open `http://localhost:8080`. Postgres (with pgvector), Redis, the API and the
web app all run as containers; migrations apply when the API starts.

### Backend

Start the database and Redis, then run the API on your machine:

```powershell
docker compose up -d db redis
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

The test suite uses a separate `source_intelligence_test` database, created
when the database container first starts.

The API runs at `http://127.0.0.1:8000`. Interactive API documentation is at
`http://127.0.0.1:8000/docs`.

### Frontend

In a second terminal:

```powershell
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.

## Optional providers

The application runs locally without keys, but the small local chat model is a
safe fallback rather than a production-quality general assistant.

Configure an OpenAI-compatible provider in `backend/.env`:

```env
CHAT_API_KEY=
CHAT_API_BASE_URL=https://api.openai.com/v1
CHAT_MODEL=gpt-4.1-mini
```

Configure compact live search:

```env
TAVILY_API_KEY=
WEB_SEARCH_ENABLED=true
SEARCH_COUNTRY=india
SEARCH_MAX_RESULTS=3
```

Never commit `.env` or paste API keys into the frontend.

## Quality checks

```powershell
cd backend
.\.venv\Scripts\pytest.exe
.\.venv\Scripts\ruff.exe check app tests scripts
.\.venv\Scripts\ruff.exe format --check app tests scripts

cd ..
npm run build
```

On Windows, the complete check can also be run from the repository root:

```powershell
.\scripts\check.ps1
```

## API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Service status |
| `GET` | `/api/documents` | List indexed documents |
| `POST` | `/api/documents` | Upload and index files |
| `DELETE` | `/api/documents/{id}` | Remove a file and its evidence |
| `POST` | `/api/query` | Ask a document, general, or live question |

## Privacy and limitations

- Uploads, indexes, API keys, logs, and local chat data are excluded from Git.
- Email addresses and phone numbers are redacted before indexing.
- Scanned PDFs require OCR and are rejected with a clear message.
- Live prices and availability can change; users should confirm them at the
  linked source.
- Browser chat history currently uses local storage and is not synchronized
  between devices.

## License

[MIT](LICENSE)
