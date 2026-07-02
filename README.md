# emotion-detection

Emotion-labeling API for Traditional Chinese text — a building block toward
scam detection (scam messages lean on urgency, fear, and pressure, which are
tonal signals). Wraps
[Johnson8187/Chinese-Emotion-Small](https://huggingface.co/Johnson8187/Chinese-Emotion-Small)
in a FastAPI service deployed to Cloud Run behind API Gateway.

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
| `GET` | `/health` | liveness — process is up |
| `GET` | `/ready` | readiness — model is loaded (Cloud Run startup probe) |
| `POST` | `/v1/emotion` | classify text into 8 emotion labels |

Errors follow a consistent contract:
`{"error": {"code": "TEXT_TOO_LONG", "message": "..."}}`.

## Configuration

All config via `APP_`-prefixed environment variables (see
[app/config.py](app/config.py)): `APP_MODEL_DIR`, `APP_CORS_ALLOW_ORIGINS`
(comma-separated origins), `APP_LOG_LEVEL`, etc. Request bodies are never
logged.
