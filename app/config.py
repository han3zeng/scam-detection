from functools import lru_cache

# Load env variables automatically, in this project the settings load docker envs.
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime config comes from environment variables prefixed with APP_."""

    model_config = SettingsConfigDict(env_prefix="APP_", protected_namespaces=())

    model_name: str = "Johnson8187/Chinese-Emotion-Small"
    # Pinned HF revision so the image content can't change under the same repo name.
    model_revision: str = "2c04ce86de44d232f0fbe31413868eb31d791aea"
    # When set (e.g. in the Docker image), load the model from this local
    # directory instead of downloading from the HuggingFace Hub.
    # Load the string from APP_MODEL_DIR in Dockerfile and overwrite None
    model_dir: str | None = None
    max_model_tokens: int = 512
    # Tests disable this and inject a fake classifier instead.
    preload_model: bool = True
    # Comma-separated list of allowed origins, e.g. "https://app.example.com".
    cors_allow_origins: str = ""
    log_level: str = "INFO"

    # --- RAG explanation feature (/v1/emotion/explain) ---
    # Off by default: requires Firestore + Vertex AI infra and ANTHROPIC_API_KEY.
    # ANTHROPIC_API_KEY is deliberately NOT a Settings field — the anthropic SDK
    # reads it from the environment, which keeps the secret out of repr()/logs.
    explain_enabled: bool = False
    gcp_project: str = ""
    vertex_location: str = "us-central1"
    embedding_model: str = "gemini-embedding-001"
    # 768 fits Firestore's 2048-dim vector-index cap (the model's native 3072
    # does not); truncated MRL vectors must be re-normalized after embedding.
    embedding_dimensions: int = 768
    firestore_database: str = "(default)"
    examples_collection: str = "emotion_examples"
    retrieval_top_k: int = 4
    explain_model: str = "claude-haiku-4-5"
    explain_max_tokens: int = 512
    anthropic_timeout_seconds: float = 15.0
    anthropic_max_retries: int = 1

    # @property let you write settings.cors_origins instead of settings.cors_origins()
    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
