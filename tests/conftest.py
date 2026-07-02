import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.model import LABELS


class FakeClassifier:
    """Stands in for EmotionClassifier so unit tests never load torch."""

    SCORES = [0.82, 0.11, 0.04, 0.01, 0.008, 0.006, 0.004, 0.002]

    def predict(self, text: str, top_k: int) -> list[dict]:
        return [
            {"label": zh, "label_en": en, "score": score}
            for (zh, en), score in list(zip(LABELS, self.SCORES, strict=True))[:top_k]
        ]


def make_settings(**overrides) -> Settings:
    return Settings(preload_model=False, **overrides)


@pytest.fixture
def client():
    app = create_app(make_settings())
    app.state.classifier = FakeClassifier()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def unready_client():
    app = create_app(make_settings())
    with TestClient(app) as test_client:
        yield test_client
