def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "bootstrap"}


def test_ready_when_model_loaded(client):
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["model"] == "Johnson8187/Chinese-Emotion-Small"
    assert body["model_revision"]


def test_ready_returns_503_before_model_loaded(unready_client):
    response = unready_client.get("/ready")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MODEL_NOT_READY"


def test_response_carries_request_id_header(client):
    response = client.get("/health")
    assert response.headers["x-request-id"]


def test_request_id_is_propagated_when_provided(client):
    response = client.get("/health", headers={"x-request-id": "abc123"})
    assert response.headers["x-request-id"] == "abc123"
