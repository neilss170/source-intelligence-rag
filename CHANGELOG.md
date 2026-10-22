# Changelog

Progress through the production build described in
[docs/REBUILD_PROMPT.md](docs/REBUILD_PROMPT.md).

## Milestone 1: Foundations (2026-10-22)

- **Infrastructure:** `docker-compose.yml` runs Postgres 16 with pgvector,
  Redis, the API and the web app. Postgres and Redis are published on host
  ports 5433 and 6380, so they don't clash with local installs. The API image
  uses CPU-only PyTorch and runs as a non-root user. The web image is nginx,
  serving the built app and proxying `/api` with buffering off, ready for
  streamed answers. It sets security headers (CSP, frame denial, nosniff,
  referrer and permissions policies) on every route.
- **Database:** SQLAlchemy 2 models and the first Alembic migration create
  users, sessions, workspaces, chats, messages and daily usage. CI checks that
  migrations apply, reverse and match the models.
- **Accounts:** sign up, log in and log out.
  - Passwords are hashed with argon2id and rehashed when the cost settings
    change.
  - Sessions are random tokens stored only as SHA-256 digests, in an
    httpOnly, SameSite=Lax cookie that is Secure outside development.
  - Every state-changing request needs a CSRF token header.
  - Logging in with an unknown email takes as long as a wrong password, and
    both give the same message.
- **Workspaces and chats:** every user gets a private workspace. Chats are
  created, renamed, deleted and listed on the server. All user data goes
  through a repository layer scoped by workspace, and another user's chat
  returns the same 404 as a missing one.
- **Errors:** every error is JSON with a stable `code`, a readable `message`
  and a `request_id`. The request ID also appears as the `X-Request-ID`
  header.
- **Health:** `/api/health` (liveness) and `/api/ready` (database and Redis
  reachable, 503 otherwise).
- **Tests:** 23 new tests, 137 in total.
  - The tests cover the full account flow, CSRF, hashed secrets, expired
    sessions, the error format and readiness.
  - The isolation suite lists every API route and fails when a new route has
    no isolation decision.

**Known gap, by design:** `/api/documents` and `/api/query` still serve the
prototype's single shared workspace. They move behind accounts in milestones
2 and 4. Until then `LEGACY_UNSCOPED_ROUTES` in `tests/test_isolation.py`
keeps the gap visible, and that list must be empty when milestone 4 is done.

## Milestone 2: Ingestion (2026-10-22)

- **Uploads are accepted at once and indexed in the background.**
  `POST /api/documents` stores the files and returns `202` with each
  document `uploaded`. An arq worker on Redis then extracts, chunks, embeds
  and indexes them; poll `GET /api/documents/{id}` for `indexing`, `ready` or
  `failed` with a readable reason. Measured in Docker with the real
  embedding model: the four evaluation documents (139 passages) indexed in
  5.2 s, and the upload request took 0.09 s.
- **Per-workspace storage:** documents, passages and spreadsheet sheets live
  in Postgres, scoped by workspace. Passages carry a 384-dimension embedding
  (HNSW cosine index) and a weighted full-text vector (GIN index, title over
  body) for hybrid search in milestone 3. The original files are kept under
  random storage keys, never derived from filenames.
- **All or nothing:** passages, tables and the `ready` status are written in
  one transaction. A document deleted while indexing stays deleted. Deleting
  a document removes its passages, tables and stored file.
- **Uploads are judged by content:**
  - PDFs must start `%PDF-`.
  - DOCX/XLSX must be real Office packages; an archive renamed `.docx` is
    refused.
  - Text formats must be UTF-8 with no binary bytes.
  - Executables and other types get a 415.
- **Limits:** per file (10 MB), per request (10 files), per workspace
  (200 MB). An oversized body is refused from its declared length or cut off
  while streaming, never buffered whole. Identical bytes re-uploaded to a
  workspace return the existing document (`duplicate: true`), even within
  one request.
- **Resilience:** if Redis is down at upload time, the document is still
  accepted. The worker sweeps every 5 minutes and re-queues documents stuck
  in `uploaded` (over 2 minutes) or `indexing` (over 30 minutes). One job
  per document, so a re-queue never indexes it twice.
- **Reuse, not rewrite:** the measured extraction, chunking and titling
  rules are reused unchanged. One shared function now defines the embedded
  text, so ingestion and search can't drift apart.
- **Compose** adds the `worker` service with a liveness check
  (`arq --check`). `.gitattributes` pins deployment files to LF line
  endings.
- **Tests:** 22 new, 159 in total. They cover upload, indexing, duplicates,
  content validation, the size limits, failure reasons, deletion,
  delete-during-indexing and the stale sweep. Isolation tests now cover
  every document route.

**Known gap:** the prototype web page still calls the old unauthenticated
document API, so it can't list or upload documents until the new sign-in UI
lands in milestone 5. `/api/query` still answers from the prototype's file
index until milestone 4.

## Milestone 3: Retrieval (2026-10-22)

- **Search runs in Postgres, per workspace.** The measured pipeline is reused
  unchanged: keyword and vector candidates (20 each), fused by reciprocal
  rank, then reranked by the cross-encoder, with probability ≥ 0.02 and the
  best 3 always kept. Only the two candidate sources are new
  (`app/retrieval/pg.py`):
  - **Keyword:** the weighted full-text column. Question words are OR-ed, so
    a passage doesn't need every word of a natural question, and identifiers
    like `SH-0042` still match exactly.
  - **Vector:** cosine distance on the HNSW index. pgvector's iterative scan
    is on, so filtering to one workspace never leaves the list short.
- **Gate met on the first run, with the same scores as the measured
  in-memory version:** recall@k 1.000, recall@1 0.950, MRR 0.975 over the 40
  fact questions; median 670 ms per search on CPU (570 ms in memory).
  `scripts/evaluate_documents.py --backend postgres --gate` indexes the
  corpus through the real worker pipeline into a throwaway workspace and
  fails below recall@k 0.95 or MRR 0.90. CI now runs it on every push with
  cached models.
- **Workspace helpers** for the next milestone: the file overview the model
  always sees, every passage in reading order with its size (for the "send
  the whole workspace" path), and the workspace's spreadsheets as a
  locked-down SQLite store loaded from the database.
- **Fixed:** files uploaded together shared one `created_at` (Postgres
  `now()` is fixed per transaction), so their order was random. Each document
  is now timestamped as it is inserted.
- **Tests:** 8 new, 167 in total. They cover OR semantics, exact
  identifiers, no results across workspaces for either search, the score
  floor, empty queries, and the helpers.

## Milestone 4: Generation (2026-10-22)

- **Answers stream.** `POST /api/chats/{id}/messages` returns server-sent
  events: `status`, `token`, `citations`, `web_sources`, `verification`,
  `done` (the stored message with mode, model, token usage and per-stage
  timings) and `error` (stable code, readable message). Through Docker and
  nginx, a document answer on a freshly started container showed its first
  token at 2.1 s and finished at 2.9 s, with retrieval 0.3 s, generation
  1.8 s and claim check 0.8 s. Ownership is checked before streaming
  starts, so another user's chat is a plain 404.
- **The measured prompt, shared.** `AnswerPrompt` builds the prompt and reads
  the reply for both the streaming service and the evaluation path, so they
  can't drift. Citation markers are resolved while streaming: a property test
  checks the streamed text matches the batch resolver under 200 random
  chunkings per case. The first characters are held until it is clear the
  reply isn't `SQL:` or `INSUFFICIENT_CONTEXT`, so those never appear on
  screen.
- **Paths:**
  - documents (whole workspace when it fits, else hybrid search), with up to
    two SQL rounds for spreadsheets;
  - general chat, when the scope says so or nothing is uploaded yet;
  - live web search, when configured and the question needs it;
  - an explicit "no documents yet" reply for document-only scope on an
    empty workspace.

  Follow-ups are rewritten into standalone questions, and the last four
  exchanges are replayed.
- **Providers:** streaming adapters for the OpenAI format (OpenAI, Groq,
  OpenRouter, Ollama, vLLM) and Anthropic's Messages API. `CHAT_MODELS` gives
  each model its own endpoint and key.
  - A rate limit under 20 s is waited out once.
  - A longer one marks the model exhausted in Redis, shared by every worker,
    and the same request moves to the next model. This happened for real
    during the smoke test.
  - A failure after the first token is not retried elsewhere.
  - When every model is out, the reply says how long until one is back.
- **Budgets:** token usage is recorded per user, model and day (an atomic
  upsert). `DAILY_TOKEN_BUDGET_PER_USER` is checked before any model call.
- **Prompt-injection defence:** the system prompt treats passages, file
  names and query results as quoted material, never instructions.
  Zero-width, bidirectional-override and control characters are stripped
  from everything taken from documents.
- **Readiness covers the models.** They load in the background at startup,
  and `/api/ready` reports `models: loading` until they're done (24 s on a
  fresh container). Before this, the first question downloaded the reranker
  and claim checker mid-request and took 16 s to its first token. Requests
  refused early (signed out, someone else's chat) never trigger a load.
- **Retired:** the prototype's unauthenticated `/api/query`.
  `LEGACY_UNSCOPED_ROUTES` is now empty: every API route requires an
  account.
- **Fixed:** a no-break space before a citation (`56 [E1]`) survived
  as a stray space in the answer. Invisible characters that had crept into
  source files as literals are now readable escapes.
- **Evaluation:** `evaluate_documents.py --backend postgres --generate` runs
  the real streaming service end to end, and `--only` picks a subset. A
  6-question smoke test with the real model scored 6/6:
  - a fact with its citation;
  - a two-source comparison;
  - an exact SQL total (€174,254.56);
  - a correct abstention;
  - the workspace question;
  - a handbook fact.

  **The full 51-question generation gate is still to run.** It uses most of
  a free Groq key's daily token allowance, which Scribe shares.
- **Tests:** 31 new, 198 in total. They cover the event stream, storage, SQL
  round trips, abstention, general and empty-workspace paths, follow-up
  rewriting, budgets, quota exhaustion, claim verification, hidden
  characters, provider parsing (OpenAI and Anthropic formats), the fallback
  chain, shared quota state in Redis and model configuration.

## Milestone 5: Frontend (2026-10-22)

- **Accounts in the UI:** sign-in and sign-up screens in the dark design.
  API errors appear as written ("Use a password of at least 10
  characters"). A session that ends returns you to sign-in. The greeting
  uses the signed-in user's first name; the hard-coded "Neil" is gone.
  Sign out lives in the sidebar's account row.
- **Everything is on the server:** chats, messages and documents come from
  the API, so browser storage is no longer used. A chat is created with its
  first question, so empty chats don't pile up, and it is titled from that
  question. Rename and delete work against the server.
- **Streaming answers:** tokens appear as they arrive, with a caret, and
  the live status sits beside the thinking dots ("Searching your
  documents", "Running a query on your spreadsheet"). Citations,
  verification and the final stored text arrive as events. The send button
  becomes a stop button; a stopped answer keeps what it had and says
  "Stopped". Failed answers show the reason and a Retry button, except when
  the daily budget is spent.
- **Documents:** upload progress shows as a percentage and a thin bar.
  Badges show "Indexing…" and "Failed" with the reason underneath, and the
  list polls while anything is indexing. The top pill counts ready
  documents or says what is indexing.
- **Fixed, found by driving the real UI:** a question asked while the only
  document was still indexing was answered as general chat ("I don't have
  any data on…"), which reads as "your file doesn't say". It now replies
  that the file is still being indexed.
- **Accessibility:** labelled controls, a radio group for the answer
  source, a polite live region for the thread, `aria-busy` while
  streaming, a progressbar role for uploads, and `aria-current` on the open
  chat.
- **Verified in a real browser through nginx** (`e2e/ui_flow.py`):
  - sign-up validation and the personal greeting;
  - upload, then indexing, then ready;
  - a streamed, cited answer in 2.3 s with the status shown first;
  - stop;
  - reload restoring the chat;
  - sign out and back in;
  - a phone-width render;
  - no CSP or script errors. The only console entry is the expected 401
    from checking for a session before signing in.
- **Tests:** 1 new backend test (199 in total) plus the browser flow.
