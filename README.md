# emotion-detection

Emotion-labeling API for Traditional Chinese text — a building block toward
scam detection (scam messages lean on urgency, fear, and pressure, which are
tonal signals). Wraps
[Johnson8187/Chinese-Emotion-Small](https://huggingface.co/Johnson8187/Chinese-Emotion-Small)
in a FastAPI service deployed to Cloud Run behind API Gateway. A RAG-based
explain endpoint additionally retrieves similar labeled sentences (Firestore
vector search) and has Claude generate a grounded explanation of *why* the
text carries its detected tone.

See [roadmap/index.md](roadmap/index.md) for the full spec and
[docs/gcp-setup.md](docs/gcp-setup.md) for the GCP setup guide.

## Development

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync                        # install deps (downloads Python 3.12 if needed)
uv run pytest                  # unit tests (model mocked, fast)
uv run pytest -m integration   # real-model test (downloads ~1.1GB first run)
uv run ruff check .            # lint
uv run uvicorn app.main:app --reload   # run locally (loads the real model)
```

Try it:

```bash
curl -s localhost:8000/v1/emotion \
  -X POST -H "Content-Type: application/json" \
  -d '{"text": "你最近過得好嗎？", "top_k": 3}' | jq .
```

The explain endpoint needs real infra: `APP_EXPLAIN_ENABLED=true`,
`APP_GCP_PROJECT` (Firestore + Vertex AI via ADC — run
`gcloud auth application-default login`), an ingested corpus
(`uv run python scripts/ingest_corpus.py <project>`), and `ANTHROPIC_API_KEY`.
See [docs/gcp-setup.md](docs/gcp-setup.md) §11.

```bash
curl -s localhost:8000/v1/emotion/explain \
  -X POST -H "Content-Type: application/json" \
  -d '{"text": "你怎麼可以這樣對我！"}' | jq .
```

## Docker

```bash
docker build -t emotion-api .
docker run --rm -p 8080:8080 emotion-api
curl localhost:8080/ready
```

The image bakes in the model at a pinned revision and uses the CPU-only
PyTorch wheel.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/docs` | interactive API documentation (Swagger UI) — no key needed |
| `GET` | `/health` | liveness — process is up |
| `GET` | `/ready` | readiness — model is loaded (Cloud Run startup probe; not exposed through the gateway) |
| `POST` | `/v1/emotion` | classify text into 8 emotion labels |
| `POST` | `/v1/emotion/explain` | classify + retrieve similar labeled examples + Claude-generated explanation of the tone |

**For frontend developers**: open `https://<gateway-host>/docs`, click
**Authorize**, and paste your API key — "Try it out" requests then go through
the gateway with the `x-api-key` header attached, so the normal quotas apply.
The docs page and `/openapi.json` are public (they're documentation); every
`/v1/*` endpoint still requires the key.

Errors follow a consistent contract:
`{"error": {"code": "TEXT_TOO_LONG", "message": "..."}}`. The explain
endpoint degrades gracefully: if retrieval or the LLM fails, the
classification is still returned with a `warnings` array
(`RETRIEVAL_UNAVAILABLE` / `EXPLANATION_UNAVAILABLE`).

## Configuration

All config via `APP_`-prefixed environment variables (see
[app/config.py](app/config.py)): `APP_MODEL_DIR`, `APP_CORS_ALLOW_ORIGINS`
(comma-separated origins), `APP_LOG_LEVEL`, etc. The RAG explain feature adds
`APP_EXPLAIN_ENABLED`, `APP_GCP_PROJECT`, and friends; the Anthropic key is
the un-prefixed `ANTHROPIC_API_KEY` env var read directly by the SDK (kept out
of `Settings` so it can't leak via config dumps).

Request bodies are never logged. Note that when the explain feature is
enabled, request text is sent to Vertex AI (embedding) and the Anthropic API
(explanation) at request time — it is still never written to logs.
