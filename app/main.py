import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

# Default settings is in config file
from app.config import Settings, get_settings
from app.embeddings import EmbeddingClient
from app.errors import AppError, register_exception_handlers
from app.explain import ExplanationGenerator
from app.logging_utils import RequestLogMiddleware, configure_logging
from app.model import EmotionClassifier
from app.retrieval import ExampleRetriever
from app.schemas import EmotionRequest, EmotionResponse, ExplainRequest, ExplainResponse

logger = logging.getLogger(__name__)


# The code before yield will be executed before application starts.
# The code after yield will be executed after applications finishes.
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
    # RAG explanation components. Clients are created lazily inside each
    # wrapper, so construction here is cheap; tests keep explain_enabled=False
    # and inject fakes instead.
    if settings.explain_enabled and getattr(app.state, "embedder", None) is None:
        app.state.embedder = EmbeddingClient(settings)
        app.state.retriever = ExampleRetriever(settings)
        app.state.explainer = ExplanationGenerator(settings)
        logger.info("explain feature enabled", extra={"model": settings.explain_model})
    yield
    retriever = getattr(app.state, "retriever", None)
    if isinstance(retriever, ExampleRetriever):
        retriever.close()
    explainer = getattr(app.state, "explainer", None)
    if isinstance(explainer, ExplanationGenerator):
        await explainer.close()


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
        return {"status": "ok", "version": "bootstrap"}

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

    # Async on purpose: retrieval and explanation are awaited I/O. The
    # CPU-bound classifier call goes through run_in_threadpool so it doesn't
    # block the event loop.
    @app.post("/v1/emotion/explain", response_model=ExplainResponse)
    async def explain(payload: ExplainRequest, request: Request) -> dict:
        state = request.app.state
        classifier = getattr(state, "classifier", None)
        if classifier is None:
            raise AppError(503, "MODEL_NOT_READY", "model is not loaded yet")
        embedder = getattr(state, "embedder", None)
        retriever = getattr(state, "retriever", None)
        explainer = getattr(state, "explainer", None)
        if embedder is None or retriever is None or explainer is None:
            raise AppError(503, "EXPLAIN_DISABLED", "explanation feature is not enabled")

        scores = await run_in_threadpool(classifier.predict, payload.text, payload.top_k)

        # Degrade gracefully: the classification is always returned; retrieval
        # or LLM failures become warnings instead of 5xx responses.
        warnings: list[dict] = []
        examples: list[dict] = []
        try:
            vector = await embedder.embed(payload.text, "RETRIEVAL_QUERY")
            examples = await retriever.find_similar(vector, payload.examples_k)
        except Exception:
            logger.exception("example retrieval failed")
            warnings.append(
                {"code": "RETRIEVAL_UNAVAILABLE", "message": "similar-example retrieval failed"}
            )

        explanation: str | None = None
        try:
            explanation = await explainer.generate(payload.text, scores, examples)
        except Exception:
            logger.exception("explanation generation failed")
            warnings.append(
                {"code": "EXPLANATION_UNAVAILABLE", "message": "explanation generation failed"}
            )

        return {
            "text": payload.text,
            "prediction": scores[0],
            "top_k": scores,
            "similar_examples": examples,
            "explanation": explanation,
            "model": settings.model_name,
            "model_revision": settings.model_revision,
            "explain_model": settings.explain_model,
            "warnings": warnings,
        }

    return app


app = create_app()
