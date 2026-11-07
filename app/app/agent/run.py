"""
CLI entrypoint for running the agent against one synthetic claim, by
claim_id, reading directly from data/synthetic/claims/claims.jsonl.

Deliberately NOT reading from the `claims` Postgres table: no loader has
populated that table with the synthetic claims yet (migrations only
created the schema, not the rows), and building a seed script is a
separate, smaller task from the agent itself. Reading claims.jsonl
directly is enough to prove the graph works end-to-end against real
retrieval/Bedrock/Postgres; wiring "POST a claim -> insert into claims ->
invoke the agent" is the REST/GraphQL API's job, later.

Usage:
    python -m app.agent.run CLM-001
    python -m app.agent.run CLM-001 --opensearch-host <real-domain-endpoint>
"""

import argparse
import json
import os
import sys
from pathlib import Path

from app.core.paths import find_repo_root

CLAIMS_FILE = find_repo_root(Path(__file__).resolve().parent) / "data" / "synthetic" / "claims" / "claims.jsonl"


def load_claim(claim_id: str) -> dict:
    with open(CLAIMS_FILE) as f:
        for line in f:
            claim = json.loads(line)
            if claim["claim_id"] == claim_id:
                return claim
    raise SystemExit(f"No claim with id {claim_id!r} found in {CLAIMS_FILE}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("claim_id")
    parser.add_argument("--opensearch-host", default=None, help="Real OpenSearch domain endpoint; omit for local docker-compose")
    parser.add_argument("--aws-profile", default="claimpilot", help="Local AWS CLI profile for Bedrock/Secrets Manager calls")
    args = parser.parse_args()

    if args.opensearch_host:
        os.environ["OPENSEARCH_HOST"] = args.opensearch_host
    os.environ.setdefault("AWS_PROFILE", args.aws_profile)

    claim = load_claim(args.claim_id)

    # Imported after env vars are set above, not at module load time -
    # app.agent.clients reads OPENSEARCH_HOST/AWS_PROFILE at call time
    # (inside each get_*_client() call), but importing late here keeps
    # the dependency order obvious rather than relying on that.
    from app.agent.graph import run_claim

    result = run_claim(claim)

    print(f"\nClaim {claim['claim_id']} ({claim['policy_type']}, {claim['claimant_state']}):")
    print(f"  {claim['text']}\n")
    print(f"Decision:        {result['decision']}")
    print(f"Confidence:      {result['confidence']:.2f}")
    print(f"Cited clauses:   {result['cited_clause_ids']}")
    print(f"Reasoning:       {result['reasoning']}")
    print(f"Retries used:    {result.get('retry_count', 0)}")
    print(f"triage_decisions.id: {result['triage_decision_id']}")

    if claim.get("is_labelled"):
        match = "MATCH" if result["decision"] == claim["expected_decision"] else "MISMATCH"
        print(f"\n[eval] expected_decision={claim['expected_decision']!r} -> {match}")
        print(f"[eval] expected_clauses={claim['expected_clauses']!r}")


if __name__ == "__main__":
    sys.exit(main())
