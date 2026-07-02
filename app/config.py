from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime config comes from environment variables prefixed with APP_."""

    model_config = SettingsConfigDict(env_prefix="APP_", protected_namespaces=())

    model_name: str = "Johnson8187/Chinese-Emotion-Small"
    # Pinned HF revision so the image content can't change under the same repo name.
    model_revision: str = "2c04ce86de44d232f0fbe31413868eb31d791aea"
    # When set (e.g. in the Docker image), load the model from this local
    # directory instead of downloading from the HuggingFace Hub.
    model_dir: str | None = None
    max_model_tokens: int = 512
    # Tests disable this and inject a fake classifier instead.
    preload_model: bool = True
    # Comma-separated list of allowed origins, e.g. "https://app.example.com".
    cors_allow_origins: str = ""
    log_level: str = "INFO"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
