"""
ClaimPilot API - FastAPI entrypoint.

Right now this is deliberately thin: just enough to build an image, push it
to ECR, and get ONE pod running on EKS end-to-end (image pull from ECR,
scheduling onto an Auto Mode node, service routing) before anything that
actually matters (the LangGraph agent, GraphQL, Postgres) is wired in.

Why /health specifically, and why it looks like this:
  - Kubernetes' liveness/readiness probes (see k8s/deployment.yaml) need an
    endpoint that returns fast and never touches the database or OpenSearch.
    If /health depended on RDS being reachable, a slow DB would make
    Kubernetes think the APP itself was unhealthy and restart a perfectly
    fine pod in a crash loop - the two failure modes need to stay separate.
  - It returns a static JSON body, not just a 200 with no body, so that when
    you `kubectl exec` in or curl it from outside, you can immediately see
    which image/version actually landed on the cluster.

When this changes: once Postgres is wired in (day 2 checklist item after
this one), a SEPARATE endpoint (e.g. /ready) should check DB connectivity.
/health should stay dependency-free for the lifetime of the project.
"""

from fastapi import FastAPI

app = FastAPI(
    title="ClaimPilot API",
    description="Agentic insurance claims-triage assistant - API layer.",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "claimpilot-api", "version": "0.1.0"}


@app.get("/")
def root() -> dict:
    return {"message": "ClaimPilot API is running. See /health and /docs."}
