# Roadmap

## Goal
[North Star](https://nordvpn.com/scam-text-checker/?srsltid=AfmBOopSHG3rMzrhukA3xY2oHgzxtwsWUoPVkqGpTRLEhBYnJ8WWKdfa)


## Overview
Originally, my plan was to make a traditional-chinese version of the NordVPN scam checker. However, after research, I reckon that traditional-chinese scam data is not available, so I pivot to an emotion-labeling service for the demo. This is still a building block toward scam detection: scam messages lean heavily on urgency, fear, and pressure — all tonal signals — so an emotion/tone classifier is a natural first component of a scam-detection pipeline.

So I should have 4 main elements.
1. Data pipeline
2. Model training and deploy pipeline
3. Backend-service
4. Frontend-service

For now I will focus on 3 and 4 since I decide to use the existing [Chinese-Emotion-Small](https://huggingface.co/Johnson8187/Chinese-Emotion-Small) model first for quick demo.



## Backend-service
Wrap FastAPI around the [Chinese-Emotion-Small](https://huggingface.co/Johnson8187/Chinese-Emotion-Small) model to provide an emotion-labeling endpoint service. The service should be a Docker container deployed to Google Cloud Run with a full CI/CD pipeline. Use Google API Gateway to handle API-key verification and quota.

Flow
```
Front end service -> api gateway -> cloud run (back end service)
```

### Milestones
- [x] **Phase 1 — Local FastAPI service + tests.** Endpoints, validation, error contract, unit tests with mocked model, one integration test with the real model. *Done when: `pytest` passes locally and the service answers `POST /v1/emotion` correctly.*
- [ ] **Phase 2 — Docker.** Multi-stage image with the model baked in, runs locally. *Done when: `docker run` serves the same requests as Phase 1.*
- [ ] **Phase 3 — Cloud Run + CI/CD.** GitHub Actions pipeline deploys on push to main, with smoke test and rollback. *Done when: a push to main produces a live, smoke-tested revision.*
- [ ] **Phase 4 — API Gateway.** Gateway in front with API key, quota, and locked-down Cloud Run ingress. *Done when: requests only succeed through the gateway with a valid key.*
- [ ] **Phase 5 — RAG emotion explanation.** `/v1/emotion/explain`: retrieve similar labeled sentences from Firestore vector search and have Claude generate a grounded explanation of the detected tone. *Done when: the endpoint is live behind the gateway with its own (lower) quota.*

The following content specifies the specs:

### CORS in FastAPI
- The back-end and front-end are on different domains, so CORS is required.
- Handling CORS in FastAPI (`CORSMiddleware`) with the google API gateway passing `OPTIONS` through, rather than relying on the gateway.

### Endpoints
2 basic endpoints
```
GET  /health          (liveness: process is up)
GET  /ready           (readiness: model is loaded and can serve)
POST /v1/emotion
```
- `/health` simply checks the service is running (liveness).
- `/ready` returns 200 only once the model is loaded into memory; wire this to Cloud Run's startup probe. The model is loaded **eagerly at startup** (not lazily on first request) so cold instances never serve a slow first prediction.
- `/v1/emotion` is a **POST** (a GET with a JSON body is nonstandard and many clients/proxies drop the body). The path is versioned (`/v1/`) so the contract can evolve without breaking clients.

### Emotion Endpoint Data Format
Request Payload

```json
{
  "text": "你最近過得好嗎？",
  "top_k": 3
}
```

Response

```json
{
  "text": "你最近過得好嗎？",
  "prediction": {
    "label": "關切語調",
    "label_en": "concerned",
    "score": 0.82
  },
  "top_k": [
    { "label": "關切語調", "label_en": "concerned", "score": 0.82 },
    { "label": "疑問語調", "label_en": "questioning", "score": 0.11 },
    { "label": "平淡語氣", "label_en": "neutral", "score": 0.04 }
  ],
  "model": "Johnson8187/Chinese-Emotion-Small",
  "model_revision": "<pinned HF commit hash>"
}
```

Note: `prediction` intentionally duplicates `top_k[0]` as a convenience field so simple clients don't need to index into the array.

### Input Validation
```python
text: str
  - empty / whitespace-only: reject (422)
  - max length: 512 characters, enforced in Pydantic
top_k: int, 1-8 (default 3)
```
The model's real limit is 512 **tokens**, not characters, and tokens ≠ characters. Policy: validate the 512-character cap in Pydantic (predictable contract for clients), then truncate at the tokenizer to the model's 512-token limit as a safety net. Truncation is silent and documented here — the API never rejects on token count.

### RAG Explanation Endpoint (`/v1/emotion/explain`)

Retrieval-augmented explanation of the classifier's verdict. Flow:

```
text → classifier (Chinese-Emotion-Small)
     → query embedding (Vertex AI gemini-embedding-001, 768 dims, L2-normalized)
     → Firestore vector search (KNN over labeled example sentences)
     → Claude (claude-haiku-4-5, Anthropic API)
     → grounded Traditional Chinese explanation citing linguistic cues + similar examples
```

- **Corpus**: [Johnson8187/Chinese_Multi-Emotion_Dialogue_Dataset](https://huggingface.co/datasets/Johnson8187/Chinese_Multi-Emotion_Dialogue_Dataset)
  (MIT, same author as the model; ~4.2k sentences using exactly the model's
  8-label taxonomy), ingested once via `scripts/ingest_corpus.py`.
- **Degradation contract**: the classification is always returned. If retrieval
  or the LLM fails, the response carries `similar_examples: []` /
  `explanation: null` plus a `warnings` array instead of a 5xx.
- **Cost guardrail**: separate gateway quota (20 req/min vs 60 for `/v1/emotion`)
  since each call spends real money (~$0.002); the deploy smoke test deliberately
  does not hit this endpoint.
- **Privacy**: request text is sent to Vertex AI and the Anthropic API at request
  time; it is still never written to logs.

Request payload:

```json
{
  "text": "你怎麼可以這樣對我！",
  "top_k": 3,
  "examples_k": 4
}
```

Response:

```json
{
  "text": "你怎麼可以這樣對我！",
  "prediction": { "label": "憤怒語調", "label_en": "angry", "score": 0.93 },
  "top_k": [ { "label": "憤怒語調", "label_en": "angry", "score": 0.93 } ],
  "similar_examples": [
    { "text": "你憑什麼這樣說！", "label": "憤怒語調", "label_en": "angry", "similarity": 0.87 }
  ],
  "explanation": "此句以質問句式「怎麼可以」直接指責對方，並以感嘆號收尾…（引用 [1]）",
  "model": "Johnson8187/Chinese-Emotion-Small",
  "model_revision": "<pinned HF commit hash>",
  "explain_model": "claude-haiku-4-5",
  "warnings": []
}
```

Warning codes (degraded-but-200 responses):

| Code | Meaning |
|---|---|
| `RETRIEVAL_UNAVAILABLE` | embedding or Firestore vector search failed; `similar_examples` is empty |
| `EXPLANATION_UNAVAILABLE` | the Anthropic call failed; `explanation` is null |

### Error Response Contract
All errors return a consistent JSON body:

```json
{
  "error": {
    "code": "TEXT_TOO_LONG",
    "message": "text exceeds 512 characters"
  }
}
```

Enumerated cases:

| Status | Code | When |
|---|---|---|
| 422 | `EMPTY_TEXT` / `TEXT_TOO_LONG` / `INVALID_TOP_K` | validation failure |
| 401 / 403 | `UNAUTHORIZED` | missing or invalid API key (returned by gateway) |
| 429 | `RATE_LIMITED` | quota exceeded (returned by gateway) |
| 500 | `INTERNAL` | unexpected failure; no internal details leaked |
| 503 | `MODEL_NOT_READY` / `EXPLAIN_DISABLED` | model not loaded yet / explain feature not enabled |

### Docker Image Strategy
- Download the model at build time and bake it into the image (avoids cold-start downloads).
- Pin the model to a specific HuggingFace **revision/commit hash**, not just the repo name — otherwise the model author can silently change what a "reproducible" image contains.
- Multi-stage build; final image contains only runtime deps.
- **CPU-only PyTorch wheel** (cuts the image from ~6GB to ~1.5GB, which directly improves Cloud Run cold starts).
- Dependencies locked with `uv` lockfile; pinned base image.
- Run as non-root user; include a `.dockerignore`.

### Cloud Run Configuration
- Memory: 2GB (model + tokenizer in memory).
- Concurrency: start low (e.g. 4–8) and tune; CPU-bound inference doesn't benefit from high concurrency.
- `min-instances`: 0 for cost (accept cold starts) — revisit to 1 if the demo needs snappy first requests.
- **`max-instances`: small hard cap (e.g. 3) as a cost guardrail.**
- Startup probe → `GET /ready`; liveness probe → `GET /health`.
- **Ingress/auth: Cloud Run requires authentication (no unauthenticated public access).** The gateway invokes it with a dedicated service account holding `roles/run.invoker`. This closes the bypass where someone discovers the `run.app` URL and skips the gateway and API key entirely.

### Google API Gateway

#### x-API-key
- Keys created via GCP API keys, **restricted to this gateway's managed service** so a leaked key can't call other GCP APIs.
- **Quota / rate limit configured on the gateway** (e.g. 60 requests/min per key). A public demo endpoint running an ML model with no rate limit is an open invitation to burn GCP credits.


### CI/CD Pipeline
Runs on **GitHub Actions**.

Pull request pipeline (no deploy):
```
PR opened/updated
  → run lint
  → run unit tests
```

Main pipeline:
```
Push to main
  → run lint
  → run unit tests
  → build Docker image (tagged with git SHA — never :latest)
  → push image to Google Artifact Registry
  → deploy to Cloud Run with --no-traffic
  → smoke test the new revision's /health and /ready
  → shift traffic to the new revision
```
- GCP auth via **Workload Identity Federation** — no downloaded service-account key JSON in GitHub secrets.
- Rollback: if the smoke test fails, traffic never shifted, so the previous revision keeps serving; delete/ignore the bad revision. Manual rollback is one command (route traffic back to the previous revision).

### Testing Strategy
- **Unit tests (fast, run on every PR):** input validation, response schema, error paths, truncation policy — with the model **mocked**.
- **Integration test (one, slower):** load the real model and assert an end-to-end prediction on a known input. Run on main pipeline (or locally) so PR CI stays fast.
- **Smoke test (deploy-time):** hit `/health` and `/ready` on the new revision before traffic shifts.

### Config Management
All config via environment variables using **Pydantic Settings**; secrets in **Secret Manager**; nothing hardcoded.

## Supporting Services
### Cloud Logging
Not optional — structured logging is table stakes.
- Structured JSON logs with a request ID on every entry.
- Request logs, error logs, latency monitoring.
- **Privacy decision: request bodies (user text) are NOT logged.** The input text is potentially sensitive (eventually scam messages, personal conversations); log only metadata (text length, top_k, latency, status).

## References
- [Scam Report - Ministry of Digital Affairs](https://fraudbuster.digiat.org.tw/accessibility/index)
- Model selection path: BERT > [XLM-RoBERTa](https://huggingface.co/FacebookAI/xlm-roberta-large) > [xlm-roberta-large-xnli](https://huggingface.co/joeddav/xlm-roberta-large-xnli) > [Chinese-Emotion-Small](https://huggingface.co/Johnson8187/Chinese-Emotion-Small) — narrowed by Chinese-language support and model size suitable for CPU serving on Cloud Run.
