# Operating Source Intelligence

How to back up, restore, watch and load-test a running stack. Every command
here was run against the Docker Compose stack while writing it.

All commands run from the repository root. On Windows Git Bash, set
`MSYS_NO_PATHCONV=1` first, or Git Bash rewrites container paths such as
`/backup` into Windows paths.

## What holds state

| Where | What | Lose it and |
| --- | --- | --- |
| Postgres volume `db-data` | Accounts, chats, messages, documents, passages with embeddings, spreadsheet rows, usage | Everything is gone |
| Volume `app-data` (`/data/files`) | The original uploaded files | Documents can't be re-indexed; answers still work from the database |
| Redis volume `redis-data` | The ingestion queue, rate-limit counters, model quota state | Queued uploads are swept up again by the worker within 5 minutes; nothing else matters |
| Volume `model-cache` | Downloaded models | They download again on the next start (slow, not harmful) |

Back up Postgres and `app-data`. Redis and the model cache don't need
backups.

## Backup

```bash
mkdir -p backups/$(date +%F)
# Database: a consistent snapshot while the stack runs.
docker compose exec -T db pg_dump -U si -Fc source_intelligence \
  > backups/$(date +%F)/db.dump
# Uploaded files.
docker run --rm -v source-intelligence-rag_app-data:/data:ro \
  -v "$PWD/backups/$(date +%F)":/backup alpine \
  tar czf /backup/files.tgz -C /data files
```

Keep backups off the machine, and encrypt them: they contain every user's
documents. The volume names are prefixed with the Compose project name
(the directory name by default); check them with `docker volume ls`.

## Restore

Stop the app first, so nothing writes while restoring:

```bash
docker compose stop api worker web
docker compose exec -T db psql -U si -d postgres \
  -c "DROP DATABASE source_intelligence" -c "CREATE DATABASE source_intelligence"
docker compose exec -T db pg_restore -U si -d source_intelligence --no-owner \
  < backups/2026-10-22/db.dump
docker run --rm -v source-intelligence-rag_app-data:/data \
  -v "$PWD/backups/2026-10-22":/backup:ro alpine \
  sh -c 'rm -rf /data/files && tar xzf /backup/files.tgz -C /data'
docker compose up -d
```

**Verified 2026-10-22.** A dump restored into a scratch database matched
the live one in every table (users, workspaces, chats, messages, documents,
passages, document_tables, usage_daily, alembic_version), and vector search
worked on the restored copy. The files archive restored into a scratch
volume gave 71 of 71 files with identical checksums.

**Practise this.** Restore into a scratch database (`CREATE DATABASE
restore_check`, then `pg_restore -d restore_check`) and compare row counts.
An untested backup is a hope, not a backup.

## Health

| Endpoint | Meaning | Use for |
| --- | --- | --- |
| `GET /api/health` | The process is up | Liveness: restart if this fails |
| `GET /api/ready` | Database, Redis and models are ready; `503` with the failing checks otherwise | Readiness: send traffic only when this passes |

After a start, `/api/ready` reports `"models": "loading"` for about 25
seconds while the embedding, reranking and claim-checking models load. The
first start also downloads them into the `model-cache` volume, which takes
longer.

The worker's health is checked by `arq --check app.worker.WorkerSettings`;
Compose runs that for you.

## Logs

Outside development, every line is one JSON object (`LOG_FORMAT=json`)
carrying the `request_id` that is also returned to the client in
`X-Request-ID`. When someone reports a problem, their request ID finds every
line of it.

- `app.access` logs one line per API request: method, route template,
  status, milliseconds.
- `app.chat.service` logs one line per answer (`"event": "answer"`):
  - `ended`: workspace, general, indexing, budget, model_quota or
    internal_error;
  - `model` and `models_called`, which show whether a fallback was used;
  - tokens in and out;
  - `latency_ms` per stage (rewrite, retrieve, generate, verify, total);
  - the citation count, groundedness, the unsupported-claim count and
    whether the answer abstained.

  Users appear as a short hash, never by email.

```bash
docker compose logs api | grep '"event": "answer"'          # every answer
docker compose logs api | grep '"ended": "model_quota"'     # quota trouble
```

## Metrics

Prometheus metrics are at `http://<api>:8000/metrics`. nginx forwards only
`/api/`, so they're not reachable from outside. Point Prometheus at the api
container directly.

| Metric | Watch for |
| --- | --- |
| `http_requests_total{route,status}` | 5xx rate by route |
| `http_request_duration_seconds` | Slow routes (time to headers; answers stream after) |
| `answers_total{mode}` | Rising `internal_error`, `model_quota` or `budget` |
| `answer_stage_seconds{stage}` | Which stage got slow: retrieve, generate, verify |
| `answer_groundedness` | A drop means answers cite sources that don't support them |
| `llm_tokens_total{model,direction}` | Spend per model |
| `llm_provider_errors_total{model,status}` | 429s are quota; 5xx is the provider |
| `llm_model_exhausted_total{model}` | How often the fallback chain is used |
| `documents{status}` | Stuck `uploaded`/`indexing` or growing `failed` |
| `ingestion_queue_depth` | Workers falling behind: add workers |

## Load testing

Load tests should measure this stack, not a model provider's rate limits,
so they use a stand-in model with fixed timing (0.35 s to the first token,
then about 0.5 s of tokens):

```bash
python backend/scripts/load/fake_llm.py &          # serves on :9100
docker compose -f docker-compose.yml -f deploy/docker-compose.loadtest.yml up -d api
python backend/scripts/load/load_test.py --users 20 --questions 5
docker compose up -d api                            # back to the real config
```

**Results, 2026-10-22, 16-core laptop CPU:**

| Run | Answers | Errors | First token p50 / p95 | Full answer p50 / p95 |
| --- | ---: | ---: | --- | --- |
| 20 users × 5 questions, before the fix | 71 | 29 | 30.8 s / 61.1 s | 60.8 s / 91.3 s |
| 20 users × 5, request session released before streaming | 100 | 0 | 2.53 s / 2.97 s | 6.86 s / 7.88 s |
| 20 users × 5, plus 2 PyTorch threads per call | 100 | 0 | 2.26 s / 2.73 s | 6.44 s / 7.47 s |
| 1 user × 10 (the latency budget) | 10 | 0 | **0.95 s** / 1.03 s | **2.18 s** / 2.27 s |

Under load the remaining cost is the claim check (median 3.5 s across 20
concurrent users, 0.8 s for one). It runs after the answer has streamed, so
it delays only the `done` event and the "unverified" note, not the text.
With a real provider, add the model's own time to first token. Groq's
gpt-oss-20b measured 0.73 s with `CHAT_REASONING_EFFORT=low` and 1.2 s
without.

## Scaling

- **More indexing throughput:** `docker compose up -d --scale worker=3`.
  Each worker indexes two documents at a time.
- **More answering throughput:** run more api replicas behind a load
  balancer that checks `/api/ready`. Quota state and rate limits live in
  Redis, so replicas share them.
- **CPU per call:** `TORCH_THREADS` (default 2). Higher helps a single
  request; lower helps many concurrent ones.

## Quotas and budgets

- **Free provider tiers run out.** Groq's free tier allows about 8,000
  tokens a minute and 200,000 a day per model. That's 50 to 60 questions a
  day on one model. List more than one model in `CHAT_FALLBACK_MODELS` or
  `CHAT_MODELS`: each has its own allowance, and the chain moves to the
  next automatically.
- **`DAILY_TOKEN_BUDGET_PER_USER`** caps one person's spend; 0 means
  unlimited.
- **Running evaluations spends real quota.** Three back-to-back full
  generation evaluations used up a 200,000-token daily allowance, and any
  other app sharing the key (Scribe shares this one) was rate-limited until
  it reset.
