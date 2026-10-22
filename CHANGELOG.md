# Changelog

Progress through the production rebuild, one milestone at a time.

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
