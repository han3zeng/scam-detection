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


class FakeEmbedder:
    """Stands in for EmbeddingClient so unit tests never call Vertex AI."""

    async def embed(self, text: str, task_type: str) -> list[float]:
        return [1.0] + [0.0] * 767


class FakeRetriever:
    """Stands in for ExampleRetriever so unit tests never call Firestore."""

    EXAMPLES = [
        {"label": "平淡語氣", "label_en": "neutral", "similarity": 0.91, "text": "今天天氣不錯。"},
        {
            "label": "平淡語氣",
            "label_en": "neutral",
            "similarity": 0.85,
            "text": "我等一下要出門。",
        },
        {
            "label": "疑問語調",
            "label_en": "questioning",
            "similarity": 0.72,
            "text": "你吃飽了嗎？",
        },
        {"label": "開心語調", "label_en": "happy", "similarity": 0.65, "text": "太好了，成功了！"},
    ]

    async def find_similar(self, vector: list[float], k: int) -> list[dict]:
        return self.EXAMPLES[:k]


class FailingRetriever:
    async def find_similar(self, vector: list[float], k: int) -> list[dict]:
        raise RuntimeError("firestore unavailable")


class FakeExplainer:
    """Stands in for ExplanationGenerator so unit tests never call Anthropic."""

    EXPLANATION = "此文本語氣平淡，句式陳述、無情緒詞彙，與例句 [1]、[2] 相似。"

    async def generate(self, text: str, scores: list[dict], examples: list[dict]) -> str:
        return self.EXPLANATION


class FailingExplainer:
    async def generate(self, text: str, scores: list[dict], examples: list[dict]) -> str:
        raise RuntimeError("anthropic unavailable")


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


_DEFAULT_CLASSIFIER = FakeClassifier()


@pytest.fixture
def make_explain_client():
    """Factory for a client with the explain components injected (overridable).

    Pass classifier=None to simulate the model not being loaded.
    """

    def factory(embedder=None, retriever=None, explainer=None, classifier=_DEFAULT_CLASSIFIER):
        app = create_app(make_settings())
        if classifier is not None:
            app.state.classifier = classifier
        app.state.embedder = embedder or FakeEmbedder()
        app.state.retriever = retriever or FakeRetriever()
        app.state.explainer = explainer or FakeExplainer()
        return TestClient(app)

    return factory


@pytest.fixture
def explain_client(make_explain_client):
    with make_explain_client() as test_client:
        yield test_client
