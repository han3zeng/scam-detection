import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.errors import AppError, register_exception_handlers
from app.logging_utils import RequestLogMiddleware, configure_logging
from app.model import EmotionClassifier
from app.schemas import EmotionRequest, EmotionResponse

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    # Eager load at startup so a cold instance never serves a slow first
    # prediction; /ready reports 200 only after this completes. Tests set
    # preload_model=False and inject a fake classifier instead.
    if settings.preload_model and getattr(app.state, "classifier", None) is None:
        logger.info("loading model", extra={"model": settings.model_name})
        classifier = EmotionClassifier(
            model_name=settings.model_name,
            revision=settings.model_revision,
            model_dir=settings.model_dir,
            max_tokens=settings.max_model_tokens,
        )
        classifier.load()
        app.state.classifier = classifier
        logger.info("model loaded")
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="emotion-detection-api", version="1.0.0", lifespan=lifespan)
    app.state.settings = settings

    app.add_middleware(RequestLogMiddleware)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type", "x-api-key"],
            max_age=3600,
        )
    register_exception_handlers(app)

    @app.get("/health")
    def health() -> dict:
        """Liveness: the process is up."""
        return {"status": "ok"}

    @app.get("/ready")
    def ready(request: Request) -> dict:
        """Readiness: the model is loaded and can serve. Wired to Cloud Run's startup probe."""
        if getattr(request.app.state, "classifier", None) is None:
            raise AppError(503, "MODEL_NOT_READY", "model is not loaded yet")
        return {
            "status": "ready",
            "model": settings.model_name,
            "model_revision": settings.model_revision,
        }

    # Sync endpoint on purpose: FastAPI runs it in a threadpool, so CPU-bound
    # inference doesn't block the event loop.
    @app.post("/v1/emotion", response_model=EmotionResponse)
    def emotion(payload: EmotionRequest, request: Request) -> dict:
        classifier = getattr(request.app.state, "classifier", None)
        if classifier is None:
            raise AppError(503, "MODEL_NOT_READY", "model is not loaded yet")
        scores = classifier.predict(payload.text, payload.top_k)
        return {
            "text": payload.text,
            "prediction": scores[0],
            "top_k": scores,
            "model": settings.model_name,
            "model_revision": settings.model_revision,
        }

    return app


app = create_app()
