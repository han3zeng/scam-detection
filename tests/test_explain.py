from tests.conftest import FailingExplainer, FailingRetriever, FakeExplainer, FakeRetriever


def test_explain_happy_path(explain_client):
    response = explain_client.post("/v1/emotion/explain", json={"text": "你最近過得好嗎？"})
    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "你最近過得好嗎？"
    assert body["prediction"] == body["top_k"][0]
    assert len(body["top_k"]) == 3
    assert body["explain_model"] == "claude-haiku-4-5"
    assert body["explanation"] == FakeExplainer.EXPLANATION
    assert body["warnings"] == []
    # default examples_k is 4
    assert len(body["similar_examples"]) == 4
    for example in body["similar_examples"]:
        assert set(example) == {"text", "label", "label_en", "similarity"}


def test_explain_top_k_and_examples_k_respected(explain_client):
    response = explain_client.post(
        "/v1/emotion/explain", json={"text": "你好", "top_k": 5, "examples_k": 2}
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["top_k"]) == 5
    assert len(body["similar_examples"]) == 2


def test_explain_validation_reuses_error_codes(explain_client):
    response = explain_client.post("/v1/emotion/explain", json={"text": ""})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EMPTY_TEXT"

    response = explain_client.post("/v1/emotion/explain", json={"text": "好" * 513})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "TEXT_TOO_LONG"

    response = explain_client.post("/v1/emotion/explain", json={"text": "你好", "top_k": 9})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_TOP_K"


def test_retrieval_failure_degrades_gracefully(make_explain_client):
    with make_explain_client(retriever=FailingRetriever()) as client:
        response = client.post("/v1/emotion/explain", json={"text": "你好"})
    assert response.status_code == 200
    body = response.json()
    assert body["similar_examples"] == []
    # explanation is still attempted without examples
    assert body["explanation"] == FakeExplainer.EXPLANATION
    assert [w["code"] for w in body["warnings"]] == ["RETRIEVAL_UNAVAILABLE"]


def test_explanation_failure_degrades_gracefully(make_explain_client):
    with make_explain_client(explainer=FailingExplainer()) as client:
        response = client.post("/v1/emotion/explain", json={"text": "你好"})
    assert response.status_code == 200
    body = response.json()
    assert body["explanation"] is None
    # classification and retrieval still succeed
    assert len(body["similar_examples"]) == 4
    assert body["prediction"] == body["top_k"][0]
    assert [w["code"] for w in body["warnings"]] == ["EXPLANATION_UNAVAILABLE"]


def test_explain_disabled_returns_503(client):
    # the plain `client` fixture has no explain components injected
    response = client.post("/v1/emotion/explain", json={"text": "你好"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "EXPLAIN_DISABLED"


def test_explain_before_model_loaded_returns_503(make_explain_client):
    with make_explain_client(classifier=None) as client:
        response = client.post("/v1/emotion/explain", json={"text": "你好"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MODEL_NOT_READY"


def test_similar_examples_come_from_retriever(explain_client):
    response = explain_client.post("/v1/emotion/explain", json={"text": "你好", "examples_k": 1})
    assert response.status_code == 200
    assert response.json()["similar_examples"] == FakeRetriever.EXAMPLES[:1]
