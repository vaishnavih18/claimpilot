"""
The LangGraph agent's state schema.

This is a TypedDict, not a Pydantic model or dataclass -- that's what every
LangGraph node signature (`def node(state: AgentState) -> dict`) and the
StateGraph constructor itself expect, and each node returns only the keys
it's updating (LangGraph merges that partial dict into the running state
for you, it isn't a full-state replace).

One design decision worth calling out: `retrieved_clauses` is a single
field that gets OVERWRITTEN on retry, not appended to. The retry's whole
point is "the first retrieval wasn't good enough" -- keeping both the bad
first attempt and the better second attempt around would just confuse the
assess step about which clauses it's supposed to be citing from. If you
ever want to show "what the first retrieval found vs. the retry" for
debugging, that's what the checkpoint history is for (every superstep is
already persisted) -- it doesn't need its own field here.
"""

from typing import TypedDict


class RetrievedClause(TypedDict):
    clause_id: str
    heading: str
    text: str
    policy_type: str
    jurisdiction: str
    scope: str
    score: float


class AgentState(TypedDict, total=False):
    # Input -- set once, at graph invocation, never written to by a node.
    claim_id: str
    claim_text: str
    policy_type: str
    claimant_state: str
    amount_claimed: int
    prior_claims_count: int

    # Written by the first retrieve_node call and reused on retry: the claim
    # text rewritten into policy wording (see nodes.expand_query).
    retrieval_query: str

    # Written by retrieve_node. Overwritten (not appended) on retry -- see
    # module docstring above.
    retrieved_clauses: list[RetrievedClause]

    # Written by assess_node. Values match app/db/models.py's
    # TriageDecision.decision exactly ("covered" | "partly_covered" |
    # "not_covered" | "unsure") -- that's deliberate, so scoring against
    # Claim.expected_decision in the eval harness is a plain string
    # comparison, no mapping table between the agent's vocabulary and the
    # synthetic data's. "unsure" is also the graph's actual fallback
    # outcome when confidence is still low after the one retry -- it
    # isn't just an unused label, see nodes.py's assess_node.
    decision: str
    confidence: float  # 0.0-1.0, the model's own self-reported confidence
    cited_clause_ids: list[str]
    reasoning: str

    # Retry bookkeeping. Starts at 0 (LangGraph fills in missing keys with
    # nothing -- retrieve_node must default this to 0 itself, see there).
    # Capped at 1 retry: this is a demo-scale safety net for a borderline
    # first retrieval, not a general-purpose "keep trying harder" loop --
    # letting it loop unbounded risks an agent that burns Bedrock calls
    # indefinitely on a genuinely ambiguous claim instead of surfacing it
    # for human review, which is the actually-correct outcome for that case.
    retry_count: int

    # Written by decide_node, for callers/tests that want it without a
    # second DB round-trip.
    triage_decision_id: str
