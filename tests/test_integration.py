"""Loads the real model end-to-end. Run with: pytest -m integration"""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def real_client():
    app = create_app(Settings())
    with TestClient(app) as test_client:
        yield test_client


def test_real_model_prediction(real_client):
    assert real_client.get("/ready").status_code == 200

    response = real_client.post("/v1/emotion", json={"text": "你最近過得好嗎？", "top_k": 8})
    assert response.status_code == 200
    body = response.json()
    assert len(body["top_k"]) == 8
    assert body["prediction"] == body["top_k"][0]
    total = sum(item["score"] for item in body["top_k"])
    assert 0.98 <= total <= 1.01
