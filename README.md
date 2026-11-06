# ClaimPilot

Agentic insurance claims-triage assistant on AWS. A LangGraph agent extracts
claim details, searches policy wording with hybrid search (OpenSearch), checks
coverage and exclusions, and drafts a cited recommendation — pausing for a
human assessor to approve, edit or reject.

**Status:** 🚧 In progress — 3-day build, started Nov 2026.

Built on AWS (ap-southeast-2) with LangGraph, Amazon Bedrock, EKS, ECS,
OpenSearch, RDS/pgvector and Terraform. Uses synthetic insurance data only.

See [docs/architecture.md](docs/architecture.md) (coming soon) for details.
