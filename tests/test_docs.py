"""The interactive docs are exposed to frontend developers through the gateway;
these tests pin the parts of the OpenAPI schema they rely on."""


def test_docs_page_served(client):
    response = client.get("/docs")
    assert response.status_code == 200
    assert "swagger-ui" in response.text.lower()


def test_openapi_schema_declares_api_key_security(client):
    schema = client.get("/openapi.json").json()
    assert schema["components"]["securitySchemes"]["ApiKeyAuth"] == {
        "type": "apiKey",
        "in": "header",
        "name": "x-api-key",
    }
    assert schema["security"] == [{"ApiKeyAuth": []}]


def test_openapi_schema_paths(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/v1/emotion" in paths
    assert "/v1/emotion/explain" in paths
    assert "/health" in paths
    # /ready is probe-only and not routed through the gateway — documenting it
    # would show consumers a path that 404s for them.
    assert "/ready" not in paths


def test_openapi_schema_has_request_examples(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert schemas["EmotionRequest"]["examples"] == [{"text": "你最近過得好嗎？", "top_k": 3}]
    assert schemas["ExplainRequest"]["examples"][0]["text"] == "你怎麼可以這樣對我！"
    assert schemas["ExplainResponse"]["examples"][0]["explain_model"] == "claude-haiku-4-5"
