"""
The graph's four nodes, plus the conditional edge function that routes
between them. See app/agent/graph.py for how they're wired together.

Why a separate prepare_retry node instead of looping assess -> retrieve
directly: a LangGraph conditional edge function is a pure read of state
that returns a next-node name - it can't also mutate state. The retry
needs retry_count incremented exactly once per retry, so that mutation
has to happen in an actual node. prepare_retry exists for that one line;
splitting it out keeps retrieve_node itself ignorant of whether it's
being called for the first time or as a retry beyond just reading
retry_count, and keeps the increment from being duplicated if retrieve_node
or assess_node's logic changes later.
"""

import uuid

from app.agent.clients import CHAT_MODEL_ID, get_bedrock_runtime_client, get_opensearch_client
from app.agent.prompts import SYSTEM_PROMPT, TRIAGE_TOOL_SPEC, build_user_message
from app.agent.retrieval import ensure_search_pipeline, hybrid_search
from app.agent.state import AgentState
from app.db.base import SessionLocal
from app.db.models import TriageDecision

# Below this, the graph spends a retry (widened retrieval, no jurisdiction
# filter) before accepting the decision. Chosen, not derived from eval
# data (there isn't any yet) - 0.6 is a deliberately middling bar: low
# enough that a clearly-matched clause (the common case) passes through
# on the first try without wasting a retry, high enough that a decision
# resting on a vague/generic clause match doesn't sail through unquestioned.
# When to change: once the eval harness (evals/) scores the agent against
# the 45 labelled claims, tune this against the actual
# confidence-vs-correctness relationship it finds - if low-confidence
# decisions turn out to usually be right anyway, this is set too high
# (wasting retries/Bedrock calls); if high-confidence decisions still miss,
# the model's confidence isn't well-calibrated and the fix is prompt
# wording (see prompts.py), not this number.
RETRY_CONFIDENCE_THRESHOLD = 0.6


def retrieve_node(state: AgentState) -> dict:
    retry_count = state.get("retry_count", 0)

    os_client = get_opensearch_client()
    ensure_search_pipeline(os_client)
    bedrock_client = get_bedrock_runtime_client()

    clauses = hybrid_search(
        os_client,
        bedrock_client,
        state["claim_text"],
        # Widen on retry: more candidates (k), and drop the jurisdiction
        # filter - see retrieval.py's hybrid_search docstring for why
        # jurisdiction (not policy_type) is the dial that moves.
        k=8 if retry_count == 0 else 15,
        policy_type=state["policy_type"],
        jurisdiction=state["claimant_state"] if retry_count == 0 else None,
    )

    return {"retrieved_clauses": clauses, "retry_count": retry_count}


def assess_node(state: AgentState) -> dict:
    bedrock_client = get_bedrock_runtime_client()

    user_message = build_user_message(
        claim_text=state["claim_text"],
        policy_type=state["policy_type"],
        claimant_state=state["claimant_state"],
        amount_claimed=state["amount_claimed"],
        prior_claims_count=state["prior_claims_count"],
        clauses=state["retrieved_clauses"],
    )

    resp = bedrock_client.converse(
        modelId=CHAT_MODEL_ID,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[{"role": "user", "content": [{"text": user_message}]}],
        toolConfig={
            "tools": [TRIAGE_TOOL_SPEC],
            # Forces this exact tool call - see prompts.py's module
            # docstring for why forced tool-use beats free-text JSON here.
            "toolChoice": {"tool": {"name": "submit_triage_decision"}},
        },
    )

    tool_use = next(
        block["toolUse"] for block in resp["output"]["message"]["content"] if "toolUse" in block
    )
    args = tool_use["input"]

    # Defensive, not decorative: the schema's `enum`/`minimum`/`maximum`
    # constrain what the model SHOULD produce, but Bedrock doesn't reject
    # a tool call whose arguments violate them - validate before this
    # lands in Postgres or drives routing, rather than trusting the model
    # output silently.
    cited = [c for c in args["cited_clause_ids"] if c in {cl["clause_id"] for cl in state["retrieved_clauses"]}]
    confidence = max(0.0, min(1.0, float(args["confidence"])))

    return {
        "decision": args["decision"],
        "confidence": confidence,
        "cited_clause_ids": cited,
        "reasoning": args["reasoning"],
    }


def route_after_assess(state: AgentState) -> str:
    if state["confidence"] < RETRY_CONFIDENCE_THRESHOLD and state.get("retry_count", 0) == 0:
        return "prepare_retry"
    return "decide"


def prepare_retry_node(state: AgentState) -> dict:
    return {"retry_count": state.get("retry_count", 0) + 1}


def decide_node(state: AgentState) -> dict:
    # If the retry ran and confidence is STILL low, the honest outcome is
    # "unsure" regardless of what the model's second attempt said - two
    # low-confidence guesses don't average into one confident answer, and
    # overriding here (rather than trusting the second assess_node call's
    # raw decision) is what actually makes the retry mean something.
    decision = state["decision"]
    if state.get("retry_count", 0) >= 1 and state["confidence"] < RETRY_CONFIDENCE_THRESHOLD:
        decision = "unsure"

    row = TriageDecision(
        id=uuid.uuid4(),
        claim_id=state["claim_id"],
        decision=decision,
        confidence=state["confidence"],
        cited_clause_ids=state["cited_clause_ids"],
        reasoning=state["reasoning"],
        model_id=CHAT_MODEL_ID,
    )

    session = SessionLocal()
    try:
        session.add(row)
        session.commit()
        decision_id = str(row.id)
    finally:
        session.close()

    return {"decision": decision, "triage_decision_id": decision_id}
