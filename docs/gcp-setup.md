# GCP Setup Guide

Everything you need to set up in Google Cloud, in order. Run these once by hand;
after that, the GitHub Actions pipeline handles every deploy.

Conventions used below — replace with your values everywhere:

| Placeholder | Meaning | Example |
|---|---|---|
| `PROJECT_ID` | your GCP project id | `emotion-demo-123456` |
| `PROJECT_NUMBER` | numeric project number (`gcloud projects describe PROJECT_ID --format='value(projectNumber)'`) | `123456789012` |
| `REGION` | region for everything | `asia-east1` (Taiwan) |
| `GITHUB_REPO` | GitHub `owner/repo` | `han3zeng/scam-detection` |

Set them as shell variables so you can paste the commands as-is:

```bash
export PROJECT_ID="your-project-id"
export REGION="asia-east1"
export GITHUB_REPO="han3zeng/scam-detection"
export PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
gcloud config set project "$PROJECT_ID"
```

---

## 1. Enable APIs
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
| `emotion-runtime` | identity the Cloud Run service *runs as* | (none needed for now) |
| `emotion-gateway` | identity API Gateway *calls Cloud Run with* | `run.invoker` on the service |
| `github-deployer` | identity GitHub Actions *deploys with* | `run.admin`, `artifactregistry.writer`, `serviceAccountUser`, `run.invoker` |

```bash
gcloud iam service-accounts create emotion-runtime  --display-name="Cloud Run runtime"
gcloud iam service-accounts create emotion-gateway  --display-name="API Gateway backend auth"
gcloud iam service-accounts create github-deployer  --display-name="GitHub Actions deployer"

export RUNTIME_SA="emotion-runtime@$PROJECT_ID.iam.gserviceaccount.com"
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
gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SA" \
  --member="serviceAccount:$DEPLOYER_SA" --role="roles/iam.serviceAccountUser"
```

## 4. Workload Identity Federation (GitHub → GCP without key files)

This lets GitHub Actions authenticate via OIDC — no downloaded service-account
key JSON sitting in GitHub secrets.

```bash
gcloud iam workload-identity-pools create github-pool \
  --location=global --display-name="GitHub Actions"

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
gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER_SA" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github-pool/attribute.repository/$GITHUB_REPO"
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
gcloud auth configure-docker "$REGION-docker.pkg.dev"

docker build -t "$REGION-docker.pkg.dev/$PROJECT_ID/emotion-detection/emotion-api:bootstrap" .
docker push "$REGION-docker.pkg.dev/$PROJECT_ID/emotion-detection/emotion-api:bootstrap"

gcloud run deploy emotion-api \
  --image "$REGION-docker.pkg.dev/$PROJECT_ID/emotion-detection/emotion-api:bootstrap" \
  --region "$REGION" \
  --platform managed \
  --no-allow-unauthenticated \
  --service-account "$RUNTIME_SA" \
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
gcloud run services add-iam-policy-binding emotion-api \
  --region "$REGION" \
  --member="serviceAccount:$GATEWAY_SA" \
  --role="roles/run.invoker"
```

Create the API, then a config from `gateway/openapi.yaml` (substituting the
real Cloud Run URL first):

```bash
gcloud api-gateway apis create emotion-api

sed "s|CLOUD_RUN_URL|$RUN_URL|g" gateway/openapi.yaml > /tmp/openapi-resolved.yaml

gcloud api-gateway api-configs create emotion-config-v1 \
  --api=emotion-api \
  --openapi-spec=/tmp/openapi-resolved.yaml \
  --backend-auth-service-account="$GATEWAY_SA"

gcloud api-gateway gateways create emotion-gateway \
  --api=emotion-api \
  --api-config=emotion-config-v1 \
  --location="$REGION"
```

Get the gateway hostname:

```bash
export GATEWAY_HOST=$(gcloud api-gateway gateways describe emotion-gateway \
  --location="$REGION" --format='value(defaultHostname)')
echo "https://$GATEWAY_HOST"
```

Note: config updates require creating a *new* config (`emotion-config-v2`, …)
and updating the gateway to point at it — configs are immutable.

## 7. API key

The gateway created a "managed service". Enable it (required before API keys
work against it), then create a key restricted to *only* that service:

```bash
export MANAGED_SERVICE=$(gcloud api-gateway apis describe emotion-api \
  --format='value(managedService)')

gcloud services enable "$MANAGED_SERVICE"

gcloud services api-keys create \
  --display-name="emotion demo frontend" \
  --api-target="service=$MANAGED_SERVICE"
```

The command prints the `keyString` — that's the value the frontend sends as
`x-api-key`. The `--api-target` restriction means a leaked key is useless
against any other Google API.

The 60 requests/minute quota is already defined in `gateway/openapi.yaml`
(`x-google-management`), so there's nothing extra to configure.

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

## Troubleshooting

- **`gcloud auth print-identity-token` fails in CI** — some gcloud versions
  can't mint ID tokens from WIF credentials directly. Fix: grant the deployer
  permission to impersonate itself and use the impersonation path:
  ```bash
  gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER_SA" \
    --member="serviceAccount:$DEPLOYER_SA" --role="roles/iam.serviceAccountTokenCreator"
  ```
  then in the workflow use
  `gcloud auth print-identity-token --impersonate-service-account="$DEPLOYER_SA" --audiences="$CANDIDATE_URL"`.
- **First CI deploy fails with a `--no-traffic` error** — you skipped step 5;
  the very first deployment of a service must take traffic.
- **Gateway returns 404 for a path that works on Cloud Run** — only paths
  declared in `gateway/openapi.yaml` are routed. `/ready` is intentionally not
  exposed through the gateway (it's for Cloud Run's startup probe only).
- **429 from the gateway** — that's the quota working; the frontend should
  surface a "try again in a minute" message.
