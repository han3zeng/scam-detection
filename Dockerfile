# ---- Stage 1: install deps + download the pinned model snapshot ----
# Use a small Python 3.12 image and name this stage builder.
FROM python:3.12-slim AS builder

# Install uv at build time
COPY --from=ghcr.io/astral-sh/uv:0.7.6 /uv /usr/local/bin/uv

# UV_LINK_MODE: copy packages instead of symlinking/hardlinking.
# UV_COMPILE_BYTECODE=1: precompile Python bytecode for faster startup.
# UV_PYTHON_DOWNLOADS=never: do not let uv download another Python version; use the Docker image’s Python.
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

# Set the working directory to /build
WORKDIR /build

# Deps first so this layer is cached across code-only changes.
# Copy dependency files first.
# This is for Docker cache. If your app code changes but dependencies do not, Docker can reuse the dependency installation layer.
COPY pyproject.toml uv.lock ./

# Python package manager uv updates the virtual environment to match the uv.lock file.
RUN uv sync --frozen --no-dev --no-install-project

# Bake the model into the image at a pinned revision: no cold-start downloads,
# and the image content can't change under the same tag.
ARG MODEL_NAME=Johnson8187/Chinese-Emotion-Small
# https://huggingface.co/Johnson8187/Chinese-Emotion-Small/commits/main
# The commit hash is the latest one at 07/03/2026
ARG MODEL_REVISION=2c04ce86de44d232f0fbe31413868eb31d791aea
COPY scripts/download_model.py scripts/
RUN .venv/bin/python scripts/download_model.py /model "$MODEL_NAME" "$MODEL_REVISION"

# ---- Stage 2: runtime ----
# Start again from a clean small Python image to keep the final image smaller because build-only files are not included.
FROM python:3.12-slim

# Create a non-root user called appuser. This is safer than running the app as root.
RUN useradd --create-home --uid 1000 appuser

# /srv stands for Service. It is a directory used to store data and files for services provided by the system, such as web server roots or database files
WORKDIR /srv

# Copy the installed virtual environment from the builder stage to service stage
COPY --from=builder /build/.venv /srv/.venv
# Copy the downloaded Hugging Face model into the final image.
COPY --from=builder /model /model
# Copy FastAPI application code into the image.
COPY app /srv/app

# Commands like uvicorn will use the version installed in .venv.
# PYTHONUNBUFFERED=1 means Python logs are printed immediately, which is useful in Cloud Run logs.
# APP_MODEL_DIR for torch to load model
ENV PATH="/srv/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    APP_MODEL_DIR=/model

USER appuser

# Document that the container listens on port 8080.
EXPOSE 8080

# Cloud Run injects PORT; our middleware emits the access log, so uvicorn's is off.
## app.main:app: inside app/main.py, find the FastAPI object named app.
## --host 0.0.0.0: listen on all network interfaces, required inside Docker/Cloud Run.
## --port ${PORT:-8080}: use Cloud Run’s injected PORT variable, or default to 8080.
## --no-access-log: disable Uvicorn’s default access log because your own middleware already logs requests.
## exec: replaces the shell process with Uvicorn, which helps signal handling during shutdown.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --no-access-log"]
