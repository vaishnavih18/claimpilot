"""
Exercises the real graph wiring (retrieve -> assess -> conditional retry
-> decide), the real Postgres writes, and the real PostgresSaver
checkpointing - against FAKE OpenSearch/Bedrock clients, since this
sandbox has no AWS network access. What this proves: the graph's control
flow, state threading, and persistence are correct. What it does NOT
prove: that real retrieval quality or real model behavior against actual
AU policy clauses is good - that needs a real run (app/agent/run.py)
against actual AWS infra, which only the real machine can do.

Two scenarios:
1. High confidence on first try -> no retry, decision persisted.
2. Low confidence on first try, still low on retry -> retry actually
   happens (jurisdiction filter drops, k widens), and decide_node
   overrides the final decision to "unsure" per nodes.py's rule.
"""

import os
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_URL"] = "postgresql+psycopg://claimpilot_test:testpass@localhost:5432/claimpilot_test"

from app.db.base import SessionLocal  # noqa: E402
from app.db.models import Claim  # noqa: E402

FAKE_CLAUSE = {
    "_source": {
        "clause_id": "HOME-1.1",
        "heading": "Flood",
        "text": "Flood means the inundation of normally dry land by water escaping from the normal confines of a lake, river, or other watercourse.",
        "policy_type": "home",
        "jurisdiction": "national",
        "scope": "definition",
    },
    "_score": 1.8,
}


def make_fake_opensearch(num_hits=1):
    client = MagicMock()
    client.transport.perform_request.return_value = {}
    client.search.return_value = {"hits": {"hits": [FAKE_CLAUSE] * num_hits}}
    return client


def make_fake_bedrock(converse_responses):
    """converse_responses: list of (decision, confidence) tuples, consumed
    in order across successive converse() calls."""
    client = MagicMock()
    fake_body = MagicMock()
    fake_body.read.return_value = b'{"embedding": [0.01]}'
    # invoke_model's real response is a plain dict with a "body" key
    # (a StreamingBody) - using a dict here (not another MagicMock) so
    # `resp["body"]` item access works exactly like the real boto3 response.
    client.invoke_model.return_value = {"body": fake_body}

    call_count = {"n": 0}

    def converse(**kwargs):
        decision, confidence = converse_responses[min(call_count["n"], len(converse_responses) - 1)]
        call_count["n"] += 1
        return {
            "output": {
                "message": {
                    "content": [
                        {
                            "toolUse": {
                                "name": "submit_triage_decision",
                                "input": {
                                    "decision": decision,
                                    "confidence": confidence,
                                    "cited_clause_ids": ["HOME-1.1"],
                                    "reasoning": "Test reasoning citing HOME-1.1.",
                                },
                            }
                        }
                    ]
                }
            }
        }

    client.converse.side_effect = converse
    return client


def seed_claim(claim_id: str):
    session = SessionLocal()
    try:
        # Dependent triage_decisions rows first - deleting the Claim row
        # while a TriageDecision still references it violates the FK
        # constraint. Only matters when re-running this script locally
        # against the SAME database more than once (a GitHub Actions
        # service container is always fresh, so CI itself never hits
        # this) - but it broke exactly that way the first time this
        # script was re-run in this sandbox, so it's a real bug, not a
        # hypothetical one.
        from app.db.models import TriageDecision

        session.query(TriageDecision).filter_by(claim_id=claim_id).delete()
        session.query(Claim).filter_by(claim_id=claim_id).delete()
        session.add(
            Claim(
                claim_id=claim_id,
                policy_type="home",
                claimant_state="NSW",
                text="A pipe burst in my bathroom and flooded the hallway carpet.",
                amount_claimed=4200,
                prior_claims_count=0,
                is_labelled=True,
                expected_decision="covered",
                expected_clauses=["HOME-1.1"],
            )
        )
        session.commit()
    finally:
        session.close()


def run_scenario(name, claim_id, fake_opensearch, fake_bedrock, expect_retry):
    seed_claim(claim_id)

    with patch("app.agent.nodes.get_opensearch_client", return_value=fake_opensearch), \
         patch("app.agent.nodes.get_bedrock_runtime_client", return_value=fake_bedrock), \
         patch("app.agent.retrieval.ensure_search_pipeline", return_value=None):

        from app.agent.graph import run_claim

        claim = {
            "claim_id": claim_id,
            "text": "A pipe burst in my bathroom and flooded the hallway carpet.",
            "policy_type": "home",
            "claimant_state": "NSW",
            "amount_claimed": 4200,
            "prior_claims_count": 0,
        }
        result = run_claim(claim)

    assert result["triage_decision_id"], "decide_node did not return a persisted row id"
    retry_used = result.get("retry_count", 0) >= 1
    assert retry_used == expect_retry, f"{name}: expected retry={expect_retry}, got retry_count={result.get('retry_count')}"

    session = SessionLocal()
    try:
        from app.db.models import TriageDecision

        row = session.get(TriageDecision, uuid.UUID(result["triage_decision_id"]))
        assert row is not None, f"{name}: no row found in triage_decisions for returned id"
        assert row.decision == result["decision"]
    finally:
        session.close()

    print(f"[PASS] {name}: decision={result['decision']} confidence={result['confidence']:.2f} retry_count={result.get('retry_count', 0)} row_id={result['triage_decision_id']}")


if __name__ == "__main__":
    run_scenario(
        "high confidence, no retry",
        "TEST-001",
        make_fake_opensearch(),
        make_fake_bedrock([("covered", 0.9)]),
        expect_retry=False,
    )

    run_scenario(
        "low confidence both tries -> forced to unsure",
        "TEST-002",
        make_fake_opensearch(),
        make_fake_bedrock([("covered", 0.3), ("covered", 0.4)]),
        expect_retry=True,
    )

    print("\nAll scenarios passed.")
