import json
# https://docs.python.org/3/library/logging.html#logging-levels
import logging
import time
import uuid
# FastAPI/Starlette handles many requests concurrently.
# We want to constrain limited-scope global value within each request.
# The instance is like a hidden key dictionary and the instance itself is the key
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
# Typing
from starlette.requests import Request
from starlette.responses import Response

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_EXTRA_FIELDS = ("method", "path", "status", "duration_ms", "model")

# 1. Create a logger instance
logger = logging.getLogger("app.access")


class JsonFormatter(logging.Formatter):
    """Structured JSON logs. The "severity" key is picked up by Cloud Logging."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict = {
            # Google Cloud Logging understands the field "severity". It will treat ERROR as error-level log
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            # The format is similar to ISO style
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
        }
        request_id = request_id_var.get()
        if request_id:
            entry["request_id"] = request_id
        for key in _EXTRA_FIELDS:
            if hasattr(record, key):
                entry[key] = getattr(record, key)
        if record.exc_info:
            entry["exc_info"] = self.formatException(record.exc_info)
        # non-ASCII characters are preserved.
        # "message": "模型載入完成" -> not like this "message": "\u6a21\u578b..."
        return json.dumps(entry, ensure_ascii=False)


def configure_logging(level: str) -> None:
    # A handler decides where logs go (e.g. standard error or standard output)
    # https://docs.python.org/3/library/logging.handlers.html#logging.StreamHandler
    # default: sys.stderr
    # In Docker / Cloud Run, logs written to stdout/stderr are collected automatically by the platform.
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    # The root logger is the top-level logger in Python logging.
    # Many other loggers eventually propagate logs to the root logger.
    root = logging.getLogger()
    # Replaces existing root handlers with your new JSON handler.
    # Remove duplicate logs or logs in different formats.
    root.handlers = [handler]
    # Set lowest threshold for the logger
    root.setLevel(level.upper())
    # Our middleware emits the access log; uvicorn's would duplicate it.
    # Raises Uvicorn’s access logger level to WARNING (Normal request logs are usually INFO), so they will be suppressed.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


class RequestLogMiddleware(BaseHTTPMiddleware):
    """One structured access-log line per request.

    Privacy: request bodies (user text) are never logged — only metadata.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["x-request-id"] = request_id
            return response
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            logger.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": status,
                    "duration_ms": duration_ms,
                },
            )
            request_id_var.reset(token)
