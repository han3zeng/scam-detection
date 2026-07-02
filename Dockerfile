# ---- Stage 1: install deps + download the pinned model snapshot ----
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.7.6 /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /build

# Deps first so this layer is cached across code-only changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Bake the model into the image at a pinned revision: no cold-start downloads,
# and the image content can't change under the same tag.
ARG MODEL_NAME=Johnson8187/Chinese-Emotion-Small
ARG MODEL_REVISION=2c04ce86de44d232f0fbe31413868eb31d791aea
COPY scripts/download_model.py scripts/
RUN .venv/bin/python scripts/download_model.py /model "$MODEL_NAME" "$MODEL_REVISION"

# ---- Stage 2: runtime ----
FROM python:3.12-slim

RUN useradd --create-home --uid 1000 appuser

WORKDIR /srv

COPY --from=builder /build/.venv /srv/.venv
COPY --from=builder /model /model
COPY app /srv/app

ENV PATH="/srv/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    APP_MODEL_DIR=/model

USER appuser

EXPOSE 8080

# Cloud Run injects PORT; our middleware emits the access log, so uvicorn's is off.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --no-access-log"]
