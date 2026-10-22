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
