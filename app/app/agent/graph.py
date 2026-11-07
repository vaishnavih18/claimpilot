"""
Wires the four nodes (app/agent/nodes.py) into the actual graph:

    retrieve -> assess -> [conditional] -> prepare_retry -> retrieve (loop)
                                       \\-> decide -> END

Checkpointed with PostgresSaver against the same Postgres instance as the
claims/triage_decisions tables (migrations/versions/0002_*.py already ran
PostgresSaver.setup() to create its tables there) - so every superstep of
every claim's run is durably persisted, not just the final decide_node
write. That's what makes a claim's run resumable (a pod restart mid-run
picks back up at the last completed node, not from scratch) and
inspectable (the checkpoint history shows exactly what the first
retrieval found vs. the retry, if a decision needs auditing later).

thread_id = claim_id: one checkpoint "conversation thread" per claim. A
claim re-triaged later (e.g. after a prompt change) reuses the same
thread_id, which means LangGraph will see prior checkpoints for it - this
graph has no memory/history-reading node that would make that ambiguous,
but it IS worth knowing: a second run isn't automatically a clean slate
unless the caller also passes a fresh config (see run.py).
"""

from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from app.agent.nodes import assess_node, decide_node, prepare_retry_node, retrieve_node, route_after_assess
from app.agent.state import AgentState


def build_graph():
    builder = StateGraph(AgentState)

    builder.add_node("retrieve", retrieve_node)
    builder.add_node("assess", assess_node)
    builder.add_node("prepare_retry", prepare_retry_node)
    builder.add_node("decide", decide_node)

    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "assess")
    builder.add_conditional_edges("assess", route_after_assess, {"prepare_retry": "prepare_retry", "decide": "decide"})
    builder.add_edge("prepare_retry", "retrieve")
    builder.add_edge("decide", END)

    return builder


@lru_cache(maxsize=1)
def get_checkpointer():
    # Raw psycopg connection, not a SQLAlchemy-pooled one - see
    # migrations/versions/0002_langgraph_checkpoints.py's comment: this is
    # the same constraint PostgresSaver.setup() hit (CREATE INDEX
    # CONCURRENTLY can't run inside a transaction block), and it applies
    # to PostgresSaver's normal runtime operation too, not just setup().
    import psycopg

    from app.core.config import get_database_url

    dsn = get_database_url().replace("postgresql+psycopg://", "postgresql://")
    connection = psycopg.connect(dsn, autocommit=True)

    from langgraph.checkpoint.postgres import PostgresSaver

    return PostgresSaver(connection)


def get_compiled_graph():
    return build_graph().compile(checkpointer=get_checkpointer())


def run_claim(claim: dict) -> dict:
    """claim: a dict with claim_id, claim_text, policy_type, claimant_state,
    amount_claimed, prior_claims_count - see app/agent/run.py for where
    these come from (currently claims.jsonl; the claims table once a real
    intake path exists)."""
    graph = get_compiled_graph()

    initial_state: AgentState = {
        "claim_id": claim["claim_id"],
        "claim_text": claim["text"],
        "policy_type": claim["policy_type"],
        "claimant_state": claim["claimant_state"],
        "amount_claimed": claim["amount_claimed"],
        "prior_claims_count": claim["prior_claims_count"],
        "retry_count": 0,
    }

    config = {"configurable": {"thread_id": claim["claim_id"]}}
    return graph.invoke(initial_state, config=config)
