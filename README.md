# ClaimPilot

**An agentic insurance-claims triage assistant, built on AWS with LangGraph and Amazon Bedrock.**

Given a home-insurance claim and a corpus of policy documents, ClaimPilot's agent retrieves the relevant clauses, reasons over them with an LLM, and returns a structured triage decision (`covered` / `partly_covered` / `not_covered` / `unsure`) with cited clauses and a confidence score — retrying its own retrieval once if it isn't confident enough the first time. The whole pipeline runs on real AWS infrastructure (EKS, RDS, OpenSearch, Bedrock), deployed and redeployed through its own CI/CD. All data is synthetic (AU home-insurance policies and claims); nothing here touches real customer data.

## Architecture

```mermaid
flowchart TB
    subgraph GH["GitHub"]
        REPO[claimpilot repo]
        ACTIONS["GitHub Actions CI/CD\n(test → build-and-push → deploy)"]
    end

    subgraph AWS["AWS (ap-southeast-2)"]
        OIDC["IAM OIDC Provider\n(scoped to repo:vaishnavih18/claimpilot,\nref:refs/heads/main)"]
        ECR["ECR\napi / mcp-server\n(IMMUTABLE tags)"]
        BEDROCK["Amazon Bedrock\nTitan Embed Text v2 +\nClaude Sonnet 4.5 (Converse,\nforced tool-use)"]

        subgraph VPC["VPC"]
            subgraph EKS["EKS Cluster (authentication_mode: API)"]
                API["claimpilot-api\nDeployment"]
            end
            RDS[("RDS Postgres + pgvector\nclaims · triage_decisions ·\nLangGraph checkpoints")]
            OS[("OpenSearch domain\npolicy-clauses index\nhybrid: BM25 + k-NN (Lucene)")]
        end

        SECRETS["Secrets Manager\nRDS master password\n(reused for OpenSearch basic auth)"]
    end

    REPO -- "push to main" --> ACTIONS
    ACTIONS -- "AssumeRoleWithWebIdentity" --> OIDC
    ACTIONS -- "build & push image (git SHA tag)" --> ECR
    ACTIONS -- "kubectl apply -k, wait for rollout" --> API
    ECR -- "pull image" --> API
    API -- "EKS Pod Identity\n(no static creds, 1 secret ARN)" --> SECRETS
    SECRETS -.-> OS
    API -- "hybrid_search()" --> OS
    API -- "read/write claims,\ndecisions, checkpoints" --> RDS
    API -- "embed_query() / converse()" --> BEDROCK
```

### Agent decision flow (LangGraph)

```mermaid
flowchart LR
    START([Claim submitted]) --> RETRIEVE["retrieve\nhybrid search → OpenSearch"]
    RETRIEVE --> ASSESS["assess\nBedrock Claude Sonnet 4.5\n(forced tool-use)"]
    ASSESS -- "confidence < 0.6\nand first attempt" --> RETRY["prepare_retry\n(mutates state)"]
    RETRY --> RETRIEVE
    ASSESS -- "confidence ≥ 0.6,\nor already retried" --> DECIDE["decide\nwrite TriageDecision row"]
    DECIDE --> END(["decision: covered / partly_covered /\nnot_covered / unsure\n+ confidence + cited clauses"])
```

A linear graph with a single conditional edge: low-confidence retrieval gets exactly one retry, not an unbounded loop. If confidence is still low after the retry, the decision is forced to `unsure` rather than returned with false certainty. Every run is checkpointed in Postgres via LangGraph's `PostgresSaver`, keyed by `claim_id`.

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Orchestration | LangGraph `StateGraph` | Explicit, inspectable state machine rather than an implicit agent loop — the retry logic is a visible edge, not hidden control flow |
| LLM | Bedrock Claude Sonnet 4.5, forced tool-use | Guaranteed structured output (decision/confidence/citations) without parsing JSON out of prose |
| Embeddings | Bedrock Titan Embed Text v2 (1024-dim) | Native Bedrock embedding, no separate embedding provider/account |
| Retrieval | OpenSearch hybrid search (BM25 + k-NN, Lucene engine) | Lucene (not NMSLIB) is required for filtered k-NN queries |
| Relational store | RDS Postgres + pgvector, SQLAlchemy/Alembic | Claims, triage decisions, and LangGraph checkpoints in one durable store |
| Compute | EKS | Container orchestration for the API; Pod Identity for credential-free AWS access |
| IaC | Terraform | VPC, RDS, OpenSearch, EKS, ECR, IAM, Secrets Manager, GitHub OIDC |
| CI/CD | GitHub Actions + OIDC | No long-lived AWS keys in GitHub; role trust scoped to this repo's `main` branch only |

## Repo structure

```
claimpilot/
├── app/
│   ├── app/
│   │   ├── agent/        # LangGraph nodes, state, prompts, graph wiring
│   │   ├── core/         # config, secrets, path resolution
│   │   └── db/           # SQLAlchemy models, session, seeding
│   ├── ingest/            # OpenSearch index creation + policy ingestion
│   ├── migrations/        # Alembic
│   ├── scripts/           # test_agent_graph.py (local + CI test harness)
│   └── requirements.txt
├── evals/                   # run_eval.py + generated eval-report.md (see Eval results)
├── frontend/                # Vite + React + Tailwind UI (landing page, Cognito sign-in, claims list/detail, run triage) + Dockerfile
├── infra/terraform/        # VPC, RDS, OpenSearch, EKS, ECR, IAM, OIDC, Pod Identity
├── k8s/                     # Kustomize manifests for the API deployment
├── data/synthetic/          # Generated AU policies + claims (no real data)
├── docker/                  # Local docker-compose Postgres, etc.
└── .github/workflows/       # ci-cd.yml
```

## Running it locally

```bash
docker compose -f docker/docker-compose.yaml up -d
```

```bash
cd app && alembic upgrade head
```

```bash
python -m app.db.seed_claims
```

```bash
python ingest/ingest.py --recreate-index
```

```bash
python -m app.agent.run CLM-001
```

Against the real AWS infra instead of local Postgres/OpenSearch, point the agent at the real OpenSearch domain and RDS instance (see `app/app/agent/clients.py` — it branches on the `OPENSEARCH_HOST` env var, using Secrets-Manager-backed basic auth when it's not `localhost`).

## Authentication & frontend deployment

Sign-in is **Google, brokered by Cognito**: the app talks OIDC (Authorization Code + PKCE, public client) to Cognito's Hosted UI, and Cognito federates to Google (`identity_provider=Google`), so no passwords are stored. Email/password remains as a fallback for admin-created users. A pre-sign-up Lambda (`infra/terraform/lambda/presignup.py`) allowlists Google accounts (`allowed_emails` / `allowed_email_domains`), because anyone with a Google account could otherwise run triage on your Bedrock budget. The browser sends the **ID token** as `Authorization: Bearer ...`, and the API validates it itself (`app/app/auth.py`: RS256 signature against the pool's JWKS, issuer, expiry, audience = app client ID, `token_use == "id"`). Every `/api/claims*` route requires it (401 otherwise; 503 if the API has no Cognito config - it fails closed); only `/health` is open. `app/scripts/test_auth.py` covers this and runs in CI.

| Piece | Where |
|---|---|
| User pool, Hosted UI domain, app client, Google identity provider, allowlist Lambda (no self sign-up) | `infra/terraform/cognito.tf` |
| Frontend ECR repo (`claimpilot/frontend`, immutable tags) | `infra/terraform/ecr.tf` (the CI role's ECR policy covers every repo in that `for_each`) |
| Frontend image: Node build -> unprivileged nginx; settings injected at start-up as `/config.js` | `frontend/Dockerfile`, `frontend/nginx/`, `frontend/docker-entrypoint.d/` |
| Auth settings for API + frontend (fill from `terraform output`, then commit) | `k8s/config.yaml` |
| Frontend Deployment/Service, Ingress (one ALB: `/api` -> API, `/` -> frontend) | `k8s/frontend-*.yaml`, `k8s/ingress.yaml` |
| ALB IngressClass (cluster-scoped, applied once by an admin - CI's role is namespace-scoped) | `k8s/cluster/ingressclass.yaml` |

**Cognito only allows `http://` callback URLs for `localhost`**, so with no domain you cannot sign in at the ALB's own `http://k8s-....elb.amazonaws.com` address (the browser also withholds `crypto.subtle`, which PKCE needs, on plain-HTTP non-localhost origins). To use the deployed stack, reach the deployed frontend through a port-forward so the origin is `http://localhost:5173`. The ALB itself is still useful: `curl http://<alb>/api/claims` returns 401 without a token.

Google setup: create a Web-application OAuth client in Google Cloud Console with redirect URI `terraform output cognito_google_redirect_uri`, then `export TF_VAR_google_client_id=... TF_VAR_google_client_secret=...` before `terraform plan/apply` (applying in a shell without them plans to *destroy* the Google provider - check the plan). `email_verified` must stay mapped or the allowlist denies everyone.

To add a domain later: Route 53 alias -> ALB, ACM certificate, certificate ARN in `k8s/cluster/ingressclass.yaml`, then set `frontend_production_url` in Terraform so Cognito registers the HTTPS callback/logout URLs. No app code changes.

## CI/CD

Three jobs, `test → build-and-push → deploy`:

- **test** runs on every push and every PR (including from a fork) with zero AWS credentials — a real Postgres service container lets it run actual Alembic migrations and the agent-graph test (`scripts/test_agent_graph.py`, using fake Bedrock/OpenSearch clients by design).
- **build-and-push** and **deploy** only run on a push to `main`, authenticate to AWS via OIDC (no stored keys), tag images by short git SHA (ECR repos are immutable), and `deploy` waits on `kubectl rollout status` so a broken image fails the pipeline instead of silently going live.

## Key design decisions

- **Retry once, not in a loop** — a second low-confidence result returns `unsure` rather than retrying indefinitely or returning false certainty.
- **Forced tool-use for the LLM call** — the decision schema is enforced by Bedrock's Converse API tool-choice, not parsed out of free text.
- **Hybrid search on Lucene, not NMSLIB** — NMSLIB doesn't support filtered k-NN at all; Lucene does, natively, since OpenSearch 2.9.
- **One Secrets Manager secret, reused** — the OpenSearch domain's basic-auth credentials are the same RDS master password, scoped to the API's Pod Identity role for exactly that one ARN, rather than a second secret.
- **GitHub Actions OIDC, scoped tightly** — the CI role's trust policy only allows `repo:vaishnavih18/claimpilot:ref:refs/heads/main`; PR runs never get AWS credentials at all.

## Eval results

`evals/run_eval.py` scores the agent against all 50 labelled claims (`is_labelled: true` in `claims.jsonl`, fields `expected_decision` / `expected_clauses`) and diagnoses every expected clause the agent failed to cite. It streams the real LangGraph node by node to capture what each retrieval try returned, with the checkpointer and the `triage_decisions` insert disabled so eval runs don't touch the audit table.

```bash
cd app
export DATABASE_URL=postgresql+psycopg://claimpilot:claimpilot_local_dev@localhost:5432/claimpilot
export AWS_PROFILE=claimpilot AWS_REGION=ap-southeast-2
python ../evals/run_eval.py          # ~10 min, sequential (Bedrock throttles under concurrency)
```

It writes `evals/eval-report.md` (summary, per-claim table, miss details) and `evals/eval-results.json` (raw). Each missed expected clause is classified as `corpus_gap`, `retrieval_miss`, `jurisdiction_filtered` or `citation_miss`; the definitions are in the script's docstring.

### Results over three iterations

Sonnet 4.5 for the assess step, 50 labelled claims, one run each. Snapshots of each run's report and raw results are kept in `evals/` (`eval-report-baseline.md`, `eval-report-query-expansion.md`, and the latest `eval-report.md`).

| | Baseline | + query expansion | + prompt change |
|---|---|---|---|
| Decision accuracy | 64% (32/50) | 68% (34/50) | **78% (39/50)** |
| Expected-clause citation recall | 73% (43/59) | 80% (47/59) | 76% (45/59) |
| `retrieval_miss` | 13 | 4 | 8 |
| `citation_miss` | 3 | 8 | 6 |
| `corpus_gap`, `jurisdiction_filtered` | 0 | 0 | 0 |
| Claims that used the retry | 16 | 14 | 5 |

**Baseline diagnosis.** The corpus was complete and the jurisdiction filter explained none of the misses; retrieval ranking was the weakness. Searching each policy type's full 45 clauses showed the missed clauses ranked 9th to 32nd, so raising `k` was not a real fix (it would need `k` of about 32, two thirds of the policy). The misses concentrated on broad "what is covered" clauses (`HOME-3.1` Scope of Cover, `HOME-3.2`, `MOTOR-3.1`): claim text like "pipe burst, water damage" matches specific peril/exclusion clauses better than the general cover clause.

**Change 1: query expansion** (`expand_query` in `nodes.py`, prompt in `prompts.py`). Before searching, Haiku 4.5 rewrites the claim into policy-clause wording (event, type of cover, relevant exclusions/conditions) and the rewrite is appended to the original claim text. It runs once and is reused on retry; if the call fails, retrieval falls back to the plain claim text. `QUERY_EXPANSION=0` disables it for A/B runs. Effect: `retrieval_miss` 13 → 4, accuracy +2 claims (within run-to-run noise on its own).

**Change 2: assess prompt.** With retrieval better, 10 of the 16 wrong decisions had every expected clause cited: the model had the right clauses and answered `unsure` anyway, because the prompt told it to say `unsure` unless a clause named the claim's specific peril. The prompt now treats a general scope-of-cover clause as sufficient basis for `covered` when no provided exclusion/limit applies, and restricts `unsure` to claims the clauses genuinely can't settle. Effect: 6 claims fixed (including the storm-damage claims), accuracy 68% → 78%.

**Open issues**

- **The labelled-`unsure` claims regressed.** All three (`CLM-029`, `CLM-030`, `CLM-049`) now get confident answers (0.85-0.95); `CLM-049` was right before the prompt change. Loosening `unsure` has a cost the other claims don't show.
- **`covered` vs `partly_covered`.** `CLM-009`, `024`, `033`, `043` are labelled `covered` but the model answers `partly_covered` because of an excess or sub-limit. The prompt rule for `partly_covered` is unchanged; whether the labels or the model are right is undecided.
- **`retrieval_miss` rose from 4 to 8 in the last run, probably as an artefact:** the model is more confident, so fewer claims reach the retry (k=15), which was acting as a safety net.
- **Still failing outright:** `CLM-001`, `CLM-011` (retrieval never surfaced `HOME-3.1` / `MOTOR-3.1`) and `CLM-031`, `CLM-041`.
- **Caveats on the numbers.** 50 claims and a non-deterministic model means a difference of 1-2 claims between runs can be noise, and the changes were tuned against these same 50 claims, so 78% is optimistic; a held-out set would give a fairer figure.

**Where to look next, by miss category.** `corpus_gap` → fix the data/labels. `retrieval_miss` → compare BM25-only vs vector-only to see which half is failing, then retune the 50/50 weighting, enrich clauses at index time (prepend section names, index "questions this clause answers"), add a reranker over the top 20-30, or try a different embedding model. `citation_miss` → prompt or model, not retrieval. `jurisdiction_filtered` → filter logic. Change one thing per run so the effect is attributable.

## Other findings

### Bugs found getting CI/CD running end-to-end

Three real, non-obvious bugs turned up only once the pipeline was run for real against live GitHub/AWS, each diagnosed from direct evidence rather than assumption:

- **`test_agent_graph.py` was clobbering CI's own `DATABASE_URL`.** The script unconditionally set `os.environ["DATABASE_URL"]` to a hardcoded local convenience value (for zero-setup local runs), which silently overrode the real service-container credentials the `test` job had already exported. Fixed with `os.environ.setdefault(...)` so CI's value wins when present, local convenience stays when it's not.
- **GitHub's OIDC token didn't match the trust policy — because GitHub has moved on.** The IAM role's trust policy was written against the "classic" `sub` claim format (`repo:owner/repo:ref:...`). A debug step added temporarily to the workflow (decode and print the actual token) showed GitHub now issues `repo:owner@owner_id/repo@repo_id:ref:...` — an immutable-ID format that survives a repo rename or ownership transfer, where the name-based version could be hijacked by whoever claims the old name afterward. The fix was to update the trust policy to the new format, not to fight it — it's the more secure option anyway.
- **A dependency that only ever existed by hand.** The `claimpilot-api` ServiceAccount (required for the EKS Pod Identity association) had been created once with an imperative `kubectl create`, never as a committed manifest. At some point it was deleted and nothing could recreate it — every `kubectl apply -k .` silently had nothing to say about it. Fixed by adding `k8s/service-account.yaml` as a tracked, kustomize-applied resource, so it's reliably recreated by CI from now on instead of depending on someone remembering a one-off command.

A broader meta-finding sits underneath all three: most of this repo (`app/`, `k8s/`, most of `infra/terraform/*.tf`) had actually never been committed to git before this pipeline was first run — only a handful of files had made it in. CI immediately surfaced that gap the first time it checked out a clean copy of the repo, which is exactly the kind of drift a CI pipeline is supposed to catch.

## Roadmap

- [x] Terraform infra (VPC, RDS, OpenSearch, EKS, ECR, IAM, Secrets Manager)
- [x] LangGraph agent (retrieve → assess → conditional retry → decide)
- [x] Real ingestion + seeding against live AWS
- [x] GitHub Actions CI/CD with OIDC
- [x] Eval harness across the full labelled claim set (64% → 78% decision accuracy over two changes; see Eval results)
- [x] Query expansion + assess-prompt change against the eval baseline
- [ ] Resolve the `unsure`-label regression and the `covered` vs `partly_covered` labels; held-out eval set
- [ ] MCP server
- [ ] GraphQL API layer
- [x] React frontend (minimal demo UI; `frontend/`)
