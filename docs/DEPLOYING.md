# Deploying Source Intelligence

This guide takes the Docker Compose stack to a single Linux server with
HTTPS. For day-to-day running (backups, logs, metrics, scaling), see
[OPERATIONS.md](OPERATIONS.md).

## What you need

- A Linux server with Docker Engine and the Compose plugin: 4 CPU cores and
  8 GB of RAM at minimum. The embedding, reranking and claim-checking models
  run on the CPU; no GPU is needed.
- About 6 GB of disk for images and models, plus room for uploads and the
  database.
- A domain name pointed at the server.
- An API key for at least one model provider: OpenAI-compatible (OpenAI,
  Groq, OpenRouter) or Anthropic. A local Ollama model also works.

## 1. Configure

```bash
git clone <this repository> && cd source-intelligence-rag
cp backend/.env.example backend/.env
```

Edit `backend/.env`. The production essentials:

| Setting | Production value | Why |
| --- | --- | --- |
| `APP_ENV` | `production` | Makes session cookies HTTPS-only and logs JSON |
| `POSTGRES_PASSWORD` | A long random string, set in the shell or a root `.env` | The default is for development only |
| `CHAT_API_KEY`, `CHAT_API_BASE_URL`, `CHAT_MODEL` | Your provider | Or `CHAT_MODELS` for one endpoint and key per model |
| `CHAT_FALLBACK_MODELS` | At least one more model | Keeps answering when the first runs out of quota |
| `DAILY_TOKEN_BUDGET_PER_USER` | Your per-user cap | Stops one user spending everyone's quota |
| `FRONTEND_ORIGIN` | `https://your.domain` | Only matters if the web app is served from a different origin |

Compose reads `POSTGRES_PASSWORD` from the environment, or from a `.env`
file next to `docker-compose.yml`. Put it there, and keep both `.env` files
out of version control (they are git-ignored).

Never put API keys in the frontend, a commit or a log. The API never logs
request headers or keys.

## 2. Put HTTPS in front

The web container serves plain HTTP on `127.0.0.1:8080`. Put a TLS proxy in
front of it. With Caddy, which obtains and renews certificates itself:

```
your.domain {
    reverse_proxy 127.0.0.1:8080 {
        flush_interval -1    # stream answers as they are written
    }
}
```

`flush_interval -1` matters: without it, a proxy may buffer the answer
stream and show the whole answer at once. nginx inside the stack already
disables buffering for `/api/`.

With `APP_ENV=production`, session cookies are `Secure` and only travel
over HTTPS, so the site must be served over HTTPS or sign-in won't stick.
Add HSTS at the TLS proxy once HTTPS works:
`header Strict-Transport-Security "max-age=31536000"` in Caddy.

## 3. Start

```bash
docker compose up -d --build
docker compose ps                      # all services healthy
curl -s localhost:8080/api/ready       # {"status":"ready",...}
```

The first start downloads the models (a few hundred MB) into the
`model-cache` volume. `/api/ready` reports `"models": "loading"` until
they're in memory. Migrations run automatically when the api starts.

## 4. Check it end to end

```bash
pip install playwright && playwright install chromium
python e2e/ui_flow.py backend/evaluation/documents/operations_report_2025.md
```

This signs up, uploads, streams an answer and checks the browser console.
It makes one real model call. Point it at your domain by editing `BASE`.

## Upgrading

```bash
git pull
docker compose up -d --build
```

The api applies new migrations before it reports healthy. Back up first
(see [OPERATIONS.md](OPERATIONS.md#backup)): migrations are tested to
apply, reverse and match the models in CI, but a backup is the real
safety net.

## Security checklist

- [ ] `APP_ENV=production`, so cookies are HTTPS-only and logs are JSON.
- [ ] A strong `POSTGRES_PASSWORD`. Postgres and Redis listen only on
  `127.0.0.1`.
- [ ] HTTPS in front, then HSTS.
- [ ] `/metrics` is not exposed publicly. nginx forwards only `/api/`;
  keep the api's port 8000 unpublished.
- [ ] Backups run, are stored off the machine, are encrypted, and have been
  restored at least once.
- [ ] A fallback model and a per-user token budget are configured.
- [ ] Rate limits suit your traffic: `RATE_LIMIT_QUESTIONS_PER_MINUTE`,
  `RATE_LIMIT_UPLOADS_PER_HOUR`, `RATE_LIMIT_AUTH_PER_15_MINUTES`.
- [ ] Contact-detail redaction is set deliberately
  (`REDACT_CONTACT_DETAILS`).
