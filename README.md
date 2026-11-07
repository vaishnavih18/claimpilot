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

## Known findings

On the first real end-to-end run against live AWS infrastructure (`CLM-001`), the agent returned `unsure` (confidence 0.20) against an expected label of `covered` — a genuine retrieval gap (one expected clause, `HOME-3.1`, never surfaced in the top results) rather than a bug. This is exactly the kind of finding the planned eval harness is meant to characterize systematically across the full labelled claim set, rather than one claim at a time.

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
- [ ] Eval harness across the full labelled claim set
- [ ] MCP server
- [ ] GraphQL API layer
- [ ] React frontend
