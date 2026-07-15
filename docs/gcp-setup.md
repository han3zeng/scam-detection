# GCP Setup Guide

Everything you need to set up in Google Cloud, in order. Run these once by hand;
after that, the GitHub Actions pipeline handles every deploy.

Conventions used below — replace with your values everywhere:

| Placeholder | Meaning | Example |
|---|---|---|
| `PROJECT_ID` | your GCP project id | `emotion-demo-123456` |
| `PROJECT_NUMBER` | numeric project number (`gcloud projects describe PROJECT_ID --format='value(projectNumber)'`) | `123456789012` |
| `REGION` | region for everything | `asia-east1` (Taiwan) |
| `GITHUB_REPO` | GitHub `owner/repo` | `han3zeng/emotion-detection` |

Set them as shell variables so you can paste the commands as-is:

```bash
export PROJECT_ID="your-project-id"
export REGION="asia-east1"
export GW_REGION="asia-northeast1"
export GITHUB_REPO="han3zeng/emotion-detection"
export PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
gcloud config set project "$PROJECT_ID"
```

---

## 1. Enable APIs
- run.googleapis.com: cloud run
- artifactregistry.googleapis.com: store docker image
- API Gateway
  - apigateway.googleapis.com
  - servicemanagement.googleapis.com
  - servicecontrol.googleapis.com
- apikeys.googleapis.com
- iamcredentials.googleapis.com 
  - Generate temporary credentials and tokens.
  - Common in secure CI/CD pipelines.
- sts.googleapis.com
  - Security Token Service
  - GitHub Actions OIDC

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  apigateway.googleapis.com \
  servicemanagement.googleapis.com \
  servicecontrol.googleapis.com \
  apikeys.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com
```

## 2. Artifact Registry (Docker image storage)

```bash
gcloud artifacts repositories create emotion-detection \
  --repository-format=docker \
  --location="$REGION" \
  --description="Images for the emotion-detection backend"
```

## 3. Service accounts

Three accounts, one per role — this separation is the production pattern:

| Account | Purpose | Roles |
|---|---|---|
| `emotion-be-runtime` | identity the Cloud Run service *runs as* | (none needed for now) |
| `emotion-gateway` | identity API Gateway *calls Cloud Run with* | `run.invoker` on the service |
| `github-deployer` | identity GitHub Actions *deploys with* | `run.admin`, `artifactregistry.writer`, `serviceAccountUser`, `run.invoker` |

```bash
gcloud iam service-accounts create emotion-be-runtime  --display-name="Cloud Run backend runtime"
gcloud iam service-accounts create emotion-gateway  --display-name="API Gateway backend auth"
gcloud iam service-accounts create github-deployer  --display-name="GitHub Actions deployer"

export BE_RUNTIME_SA="emotion-be-runtime@$PROJECT_ID.iam.gserviceaccount.com"
export GATEWAY_SA="emotion-gateway@$PROJECT_ID.iam.gserviceaccount.com"
export DEPLOYER_SA="github-deployer@$PROJECT_ID.iam.gserviceaccount.com"
```

Grant the deployer what it needs:

```bash
# deploy Cloud Run revisions
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$DEPLOYER_SA" --role="roles/run.admin"

# push images
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$DEPLOYER_SA" --role="roles/artifactregistry.writer"

# invoke the (private) service for the deploy-time smoke test
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$DEPLOYER_SA" --role="roles/run.invoker"

# allowed to deploy *as* the runtime SA
gcloud iam service-accounts add-iam-policy-binding "$BE_RUNTIME_SA" \
  --member="serviceAccount:$DEPLOYER_SA" --role="roles/iam.serviceAccountUser"

# allowed to mint ID tokens as itself. Required by the CI smoke test: WIF
# credentials can produce access tokens but not ID tokens, so the workflow
# calls the private Cloud Run URL with
#   gcloud auth print-identity-token --impersonate-service-account=$DEPLOYER_SA
# and that impersonation needs this grant (yes, the SA impersonating itself).
gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER_SA" \
  --member="serviceAccount:$DEPLOYER_SA" --role="roles/iam.serviceAccountTokenCreator"
```

## 4. Workload Identity Federation (GitHub → GCP without key files)

This lets GitHub Actions authenticate via OIDC — no downloaded service-account
key JSON sitting in GitHub secrets.

**Side Notes**

**OIDC**
Traditional identity verification causes The Password Proliferation Crisis, i.e., user may have different accounts and passwords for different services. The OAuth tackles the application layer problem through granting access permission to different apps from single account. On the other hand, OIDC enables universal Single Sign-On (SSO), creates a centralized identity Provider like Oka. 

**Workload identity pools**
Workload identity pools allow non-Google Cloud applications and services (like those running in AWS, Azure, or GitHub) to securely access Google Cloud resources. They eliminate the need to manually create, rotate, and secure long-lived service account keys by using Workload Identity Federation to grant short-lived, temporary access via IAM.
```bash
# Creates a container (the pool) to manage external identities
gcloud iam workload-identity-pools create github-pool \
  --location=global --display-name="GitHub Actions"

# Creates a "provider" inside the pool `github-pool`. This tells Google Cloud to trust GitHub's authentication system
gcloud iam workload-identity-pools providers create-oidc github-provider \
  --location=global \
  --workload-identity-pool=github-pool \
  --display-name="GitHub OIDC" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository == '$GITHUB_REPO'"
```

The `attribute-condition` is the security boundary: only workflows from *your*
repo can exchange tokens. Now allow that identity to impersonate the deployer:

```bash
# This command grants GitHub repository $GITHUB_REPO permission to impersonate Google Cloud Service Account $DEPLOYER_SA.
gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER_SA" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github-pool/attribute.repository/$GITHUB_REPO"

# echo: projects/737991661671/locations/global/workloadIdentityPools/github-pool/providers/github-provider
```

Note the full provider resource name — you'll put it in GitHub:

```bash
echo "projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github-pool/providers/github-provider"
```

## 5. First deploy (manual bootstrap)

The CI pipeline deploys with `--no-traffic`, which isn't allowed on a service's
very first deployment — so create the service once by hand. This also builds
the image locally (~10–20 min the first time; the model download is ~1.1GB):

```bash
# Configures the local Docker client to use Google Cloud Artifact Registry for image pushing and pulling 
gcloud auth configure-docker "$REGION-docker.pkg.dev"

# Creates image at current folder `.` tag it with strict cloud address and an explicit version label named :bootstrap.
docker build -t "$REGION-docker.pkg.dev/$PROJECT_ID/emotion-detection/emotion-api:bootstrap" .

# Build with emulating amd64 chip 
docker buildx build --platform linux/amd64 -t "$REGION-docker.pkg.dev/$PROJECT_ID/emotion-detection/emotion-api:bootstrap" .          

# Push to google cloud artifact registry
docker push "$REGION-docker.pkg.dev/$PROJECT_ID/emotion-detection/emotion-api:bootstrap"

# Instructs Google Cloud to deploy or update a service named emotion-api.
# --platform managed: Tells Google to handle all server maintenance, scaling, and infrastructure configurations automatically.
# --no-allow-unauthenticated: Locks the endpoint down so only verified clients with proper IAM credentials can call it.
# --service-account: Grants your running application specific cloud identities and permissions via an IAM service account variable.
# --concurrency 8:  Limits each single container instance to handling a maximum of 8 simultaneous requests at once.
# --timeout 60 --port 8080: Kills any request taking longer than 60 seconds, and routes incoming web traffic into port 8080 inside your container.
# --startup-probe: Tells Cloud Run how to verify your app is fully loaded before routing users to it.
## The breakdown: It waits 10 seconds (initialDelaySeconds), then pings your /ready endpoint every 10 seconds (periodSeconds). It gives the app up to 3 minutes to pass (18 failures × 10 seconds) before declaring the deployment a failure.
gcloud run deploy emotion-api \
  --image "$REGION-docker.pkg.dev/$PROJECT_ID/emotion-detection/emotion-api:bootstrap" \
  --region "$REGION" \
  --platform managed \
  --no-allow-unauthenticated \
  --service-account "$BE_RUNTIME_SA" \
  --memory 2Gi --cpu 2 \
  --concurrency 8 \
  --min-instances 0 --max-instances 3 \
  --timeout 60 --port 8080 \
  --startup-probe "httpGet.path=/ready,httpGet.port=8080,initialDelaySeconds=10,periodSeconds=10,failureThreshold=18,timeoutSeconds=5"
```

Key flags and why:
- `--no-allow-unauthenticated` — **the security boundary.** Nobody can call the
  `run.app` URL directly; only identities with `run.invoker` (the gateway and
  the deployer) can. This is what stops people from bypassing your API key.
- `--max-instances 3` — cost guardrail. Worst case is 3 instances, not 100.
- `--startup-probe` on `/ready` — Cloud Run won't route traffic to an instance
  until the model is actually loaded.

Verify it's private (should print 403):

```bash
export RUN_URL=$(gcloud run services describe emotion-api --region "$REGION" --format='value(status.url)')
curl -s -o /dev/null -w '%{http_code}\n' "$RUN_URL/health"
```

And that it works with credentials (should print JSON):

```bash
# Use the identity of the account showed by `gcloud config get-value account`
curl -s -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$RUN_URL/health"
```

If you want CORS for your frontend domain, add it now (comma-separated origins):

```bash
gcloud run services update emotion-api --region "$REGION" \
  --set-env-vars "APP_CORS_ALLOW_ORIGINS=https://your-frontend.example.com"
```

## 6. API Gateway

Let the gateway's service account invoke the private Cloud Run service:

```bash
# Updates the security policy (IAM) for the Cloud Run service named emotion-api
gcloud run services add-iam-policy-binding emotion-api \
  --region "$REGION" \
  --member="serviceAccount:$GATEWAY_SA" \
  --role="roles/run.invoker"
```

Create the API, then a config from `gateway/openapi.yaml` (substituting the
real Cloud Run URL first):

```bash
# Creates a new API Gateway container named emotion-api
# It is a logical container used for configuration management.
# https://console.cloud.google.com/api-gateway
gcloud api-gateway apis create emotion-api

sed "s|CLOUD_RUN_URL|$RUN_URL|g" gateway/openapi.yaml > /tmp/openapi-resolved.yaml

# Uploads local OpenAPI yaml file and registers it as a specific blueprint version (emotion-config-v1) inside your GCP project.
gcloud api-gateway api-configs create emotion-config-v1 \
  --api=emotion-api \
  --openapi-spec=/tmp/openapi-resolved.yaml \
  --backend-auth-service-account="$GATEWAY_SA"

# Creates the actual, live internet endpoint
# This is the actual public-facing proxy that takes live internet traffic and routes it to the Cloud Run.
# There is no asia-east available
gcloud api-gateway gateways create emotion-gateway \
  --api=emotion-api \
  --api-config=emotion-config-v1 \
  --location="$GW_REGION"
```

Get the gateway hostname:

```bash
export GATEWAY_HOST=$(gcloud api-gateway gateways describe emotion-gateway \
  --location="$GW_REGION" --format='value(defaultHostname)')
echo "https://$GATEWAY_HOST"
```

Note: config updates require creating a *new* config (`emotion-config-v2`, …)
and updating the gateway to point at it — configs are immutable.

## 7. API key

The gateway created a "managed service". Enable it (required before API keys
work against it), then create a key restricted to *only* that service:

```bash
# MANAGED_SERVICE is the ID for emotion-api gateway service for registering in API registry
export MANAGED_SERVICE=$(gcloud api-gateway apis describe emotion-api \
  --format='value(managedService)')

gcloud services enable "$MANAGED_SERVICE"

# Create an api-keys only consume MANAGED_SERVICE
gcloud services api-keys create \
  --display-name="emotion demo frontend" \
  --api-target="service=$MANAGED_SERVICE"
```

The command prints the `keyString` — that's the value the frontend sends as
`x-api-key`. The `--api-target` restriction means a leaked key is useless
against any other Google API.

The 60 requests/minute quota is already defined in `gateway/openapi.yaml`
(`x-google-management`), so there's nothing extra to configure.


```bash
# List all created api-keys
gcloud services api-keys list
# Get the key string based on the resource name of the key
gcloud services api-keys get-key-string "$name" 

```

## 8. Test end-to-end

```bash
export API_KEY="paste-the-keyString-here"

# no key → 401/403
curl -s -o /dev/null -w '%{http_code}\n' "https://$GATEWAY_HOST/v1/emotion" \
  -X POST -H "Content-Type: application/json" -d '{"text":"你好"}'

# with key → 200 with prediction
curl -s "https://$GATEWAY_HOST/v1/emotion" \
  -X POST \
  -H "Content-Type: application/json" \
  -H "x-api-key: $API_KEY" \
  -d '{"text": "你最近過得好嗎？", "top_k": 3}' | jq .

# direct Cloud Run URL still blocked → 403
curl -s -o /dev/null -w '%{http_code}\n' "$RUN_URL/health"
```

## 9. GitHub repository configuration

In the GitHub repo → Settings → Secrets and variables → Actions → **Variables**
(none of these are secret — WIF means there are no key files):

| Variable | Value |
|---|---|
| `GCP_PROJECT_ID` | `PROJECT_ID` |
| `GCP_REGION` | `REGION` |
| `CLOUD_RUN_SERVICE` | `emotion-api` |
| `ARTIFACT_REGISTRY_REPO` | `emotion-detection` |
| `GCP_RUNTIME_SA` | `emotion-runtime@PROJECT_ID.iam.gserviceaccount.com` |
| `GCP_DEPLOYER_SA` | `github-deployer@PROJECT_ID.iam.gserviceaccount.com` |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | the `projects/…/providers/github-provider` string from step 4 |

After this, every push to `main` runs: lint → unit tests → build → push →
deploy with `--no-traffic` → smoke test the candidate revision → shift traffic.
If the smoke test fails, traffic never moves and the previous revision keeps
serving — rollback is automatic-by-default.

Manual rollback, if you ever need it:

```bash
gcloud run revisions list --service emotion-api --region "$REGION"
gcloud run services update-traffic emotion-api --region "$REGION" \
  --to-revisions=PREVIOUS_REVISION_NAME=100
```

## 10. Cost guardrails

- `--max-instances 3` is already set; that caps the worst case.
- Set a **budget alert**: Console → Billing → Budgets & alerts → create a
  budget (e.g. $10/month) with email alerts at 50/90/100%.
- The gateway quota (60 req/min per key) caps sustained abuse through the
  front door.

## 11. RAG explanation feature (`/v1/emotion/explain`)

The explain endpoint adds three external dependencies: **Firestore** (vector
search over labeled example sentences), **Vertex AI** (`gemini-embedding-001`
embeddings), and the **Anthropic API** (`claude-haiku-4-5` generates the
explanation). Everything below is one-time setup; the feature is toggled with
`APP_EXPLAIN_ENABLED` (the deploy pipeline sets it).

### 11.1 Enable APIs
- apiplatform (Vertex AI): a unified development platform used to build, train, deploy, and manage machine learning (ML) models and AI agents

```bash
gcloud services enable \
  firestore.googleapis.com \
  aiplatform.googleapis.com \
  secretmanager.googleapis.com
```

### 11.2 Firestore database + vector index

```bash
# Skip if the project already has a Firestore database.
gcloud firestore databases create --location="$REGION" --type=firestore-native

# KNN vector index — required before find_nearest() queries work.
# dimension must match APP_EMBEDDING_DIMENSIONS (768; Firestore caps vector
# indexes at 2048 dims, which is why we don't use the gemini-embedding-001 model's native 3072).
gcloud firestore indexes composite create \
  --collection-group=emotion_examples \
  --query-scope=COLLECTION \
  --field-config=field-path=embedding,vector-config='{"dimension":"768","flat":"{}"}' \
  --database="(default)"
```

### 11.3 Runtime service-account permissions

The Cloud Run runtime SA (`emotion-be-runtime`) now needs to read Firestore
and call Vertex AI:

```bash
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$BE_RUNTIME_SA" --role="roles/datastore.user"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$BE_RUNTIME_SA" --role="roles/aiplatform.user"
```

### 11.4 Anthropic API key in Secret Manager

The key is injected into Cloud Run as the `ANTHROPIC_API_KEY` env var by the
deploy pipeline (`--set-secrets`). It is deliberately *not* an `APP_`-prefixed
setting so it never appears in config dumps or logs.

```bash
# --data-file=- : the data is from the std input
printf '%s' "your-anthropic-api-key" | gcloud secrets create anthropic-api-key --data-file=-

# Let the BE_RUNTIME_SA service account to access the anthropic-api-key
gcloud secrets add-iam-policy-binding anthropic-api-key \
  --member="serviceAccount:$BE_RUNTIME_SA" --role="roles/secretmanager.secretAccessor"
```

### 11.5 Ingest the example corpus

Embeds the labeled corpus and upserts it into the `emotion_examples`
collection (~4.2k docs, one-time cost ≈ $0.02, idempotent — safe to re-run):

```bash
gcloud auth application-default login
uv run python scripts/ingest_corpus.py "$PROJECT_ID"        # add --dry-run to preview
```

Corpus: [Johnson8187/Chinese_Multi-Emotion_Dialogue_Dataset](https://huggingface.co/datasets/Johnson8187/Chinese_Multi-Emotion_Dialogue_Dataset)
(MIT license, same author as the classifier model). It uses exactly the
model's 8-label taxonomy — every label, including `關切語調` (concerned), has
several hundred example sentences. Rows with any other label would be skipped
defensively and reported by the script.

### 11.6 Gateway config update

`gateway/openapi.yaml` already declares `/v1/emotion/explain` with its own
quota (20 req/min — each call costs real money, so the cap bounds worst-case
spend at roughly $3/day). Gateway configs are immutable, so publish a new one:

```bash
sed "s|CLOUD_RUN_URL|$RUN_URL|g" gateway/openapi.yaml > /tmp/openapi-resolved.yaml

gcloud api-gateway api-configs create emotion-config-v2 \
  --api=emotion-api \
  --openapi-spec=/tmp/openapi-resolved.yaml \
  --backend-auth-service-account="$GATEWAY_SA"

gcloud api-gateway gateways update emotion-gateway \
  --api=emotion-api \
  --api-config=emotion-config-v2 \
  --location="$GW_REGION"
```

### 11.7 Privacy note

Request bodies are still never written to logs. But with the explain feature
enabled, the input text **does leave the service** at request time: it is sent
to Vertex AI (to compute the query embedding) and to the Anthropic API (to
generate the explanation). Document this in any user-facing privacy statement.

### 11.8 Test it

```bash
curl -s "https://$GATEWAY_HOST/v1/emotion/explain" \
  -X POST \
  -H "Content-Type: application/json" \
  -H "x-api-key: $API_KEY" \
  -d '{"text": "你怎麼可以這樣對我！"}' | jq .
```

Expect an `angry` prediction, a `similar_examples` list with similarity
scores, and a 2–4 sentence Traditional Chinese `explanation`. If `warnings`
contains `RETRIEVAL_UNAVAILABLE` or `EXPLANATION_UNAVAILABLE`, the
corresponding backend (Firestore/Vertex or Anthropic) failed — the
classification itself still succeeds.

## 12. Interactive API docs for frontend developers

`gateway/openapi.yaml` routes `GET /docs` (Swagger UI served by FastAPI) and
`GET /openapi.json` through the gateway **without** an API key — they are
documentation, not data. The security model is unchanged:

- every `/v1/*` endpoint still requires `x-api-key` and its quota;
- Cloud Run still rejects direct (non-gateway) calls;
- in the docs UI, developers click **Authorize** and paste their API key, so
  "Try it out" requests carry `x-api-key` through this same gateway;
- `/ready` is hidden from the schema (probe-only, not routed here).

Publishing the change is the usual immutable-config dance (bump the version
number from whatever is currently live):

```bash
sed "s|CLOUD_RUN_URL|$RUN_URL|g" gateway/openapi.yaml > /tmp/openapi-resolved.yaml

gcloud api-gateway api-configs create emotion-config-v3 \
  --api=emotion-api \
  --openapi-spec=/tmp/openapi-resolved.yaml \
  --backend-auth-service-account="$GATEWAY_SA"

gcloud api-gateway gateways update emotion-gateway \
  --api=emotion-api \
  --api-config=emotion-config-v3 \
  --location="$GW_REGION"
```

Then share `https://$GATEWAY_HOST/docs` plus an API key with the frontend
developer:

```bash
# docs page loads without a key
curl -s -o /dev/null -w '%{http_code}\n' "https://$GATEWAY_HOST/docs"        # 200
curl -s "https://$GATEWAY_HOST/openapi.json" | jq '.info.title'             # "emotion-detection-api"

# data endpoints still gated
curl -s -o /dev/null -w '%{http_code}\n' "https://$GATEWAY_HOST/v1/emotion" \
  -X POST -H "Content-Type: application/json" -d '{"text":"你好"}'          # 401/403
```

## Troubleshooting

- **`gcloud auth print-identity-token` fails in CI with "No identity token can
  be obtained from the current credentials"** — WIF credentials can't mint ID
  tokens directly; the smoke test must impersonate the deployer SA (the
  workflow already does). Make sure you granted
  `roles/iam.serviceAccountTokenCreator` to the deployer SA on itself
  (section 3).
- **First CI deploy fails with a `--no-traffic` error** — you skipped step 5;
  the very first deployment of a service must take traffic.
- **Gateway returns 404 for a path that works on Cloud Run** — only paths
  declared in `gateway/openapi.yaml` are routed. `/ready` is intentionally not
  exposed through the gateway (it's for Cloud Run's startup probe only).
- **429 from the gateway** — that's the quota working; the frontend should
  surface a "try again in a minute" message.
