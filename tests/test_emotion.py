def test_predict_happy_path(client):
    response = client.post("/v1/emotion", json={"text": "你最近過得好嗎？"})
    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "你最近過得好嗎？"
    assert body["model"] == "Johnson8187/Chinese-Emotion-Small"
    assert body["model_revision"]
    # prediction is a convenience duplicate of top_k[0]
    assert body["prediction"] == body["top_k"][0]
    # default top_k is 3
    assert len(body["top_k"]) == 3
    scores = [item["score"] for item in body["top_k"]]
    assert scores == sorted(scores, reverse=True)
    for item in body["top_k"]:
        assert set(item) == {"label", "label_en", "score"}


def test_top_k_is_respected(client):
    response = client.post("/v1/emotion", json={"text": "你好", "top_k": 8})
    assert response.status_code == 200
    assert len(response.json()["top_k"]) == 8


def test_empty_text_rejected(client):
    response = client.post("/v1/emotion", json={"text": ""})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EMPTY_TEXT"


def test_whitespace_only_text_rejected(client):
    response = client.post("/v1/emotion", json={"text": "   \n\t "})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EMPTY_TEXT"


def test_missing_text_rejected(client):
    response = client.post("/v1/emotion", json={"top_k": 3})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EMPTY_TEXT"


def test_text_too_long_rejected(client):
    response = client.post("/v1/emotion", json={"text": "好" * 513})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "TEXT_TOO_LONG"


def test_text_at_max_length_accepted(client):
    response = client.post("/v1/emotion", json={"text": "好" * 512})
    assert response.status_code == 200


def test_top_k_out_of_range_rejected(client):
    for bad_top_k in (0, 9, -1):
        response = client.post("/v1/emotion", json={"text": "你好", "top_k": bad_top_k})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_TOP_K"


def test_wrong_method_uses_error_contract(client):
    response = client.get("/v1/emotion")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


def test_unknown_path_uses_error_contract(client):
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_predict_before_model_loaded_returns_503(unready_client):
    response = unready_client.post("/v1/emotion", json={"text": "你好"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MODEL_NOT_READY"
