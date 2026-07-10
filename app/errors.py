import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

_HTTP_STATUS_CODES = {
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    429: "RATE_LIMITED",
}


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def _map_validation_error(exc: RequestValidationError) -> tuple[str, str]:
    first = exc.errors()[0]
    field = first["loc"][-1] if first["loc"] else None
    err_type = first["type"]
    message = first["msg"]

    if field == "text":
        if err_type == "string_too_long":
            return "TEXT_TOO_LONG", message
        if err_type in ("empty_text", "missing", "string_type"):
            return "EMPTY_TEXT", message
    if field == "top_k":
        return "INVALID_TOP_K", message
    return "VALIDATION_ERROR", message


# Add custom error handler: https://fastapi.tiangolo.com/tutorial/handling-errors/#install-custom-exception-handlers
def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        code, message = _map_validation_error(exc)
        return error_response(422, code, message)

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return error_response(exc.status_code, exc.code, exc.message)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_STATUS_CODES.get(exc.status_code, "HTTP_ERROR")
        return error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        # Log the real error; never leak internals to the client.
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return error_response(500, "INTERNAL", "internal server error")
