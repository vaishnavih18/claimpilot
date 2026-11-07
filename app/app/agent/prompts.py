"""
The assess step's system prompt and forced-tool-call schema.

Structured output via a FORCED tool call (toolChoice naming the tool
directly), not "ask the model to reply with a JSON block and regex/
json.loads the response" - the forced-tool approach means Bedrock's own
API guarantees the response IS that tool call with arguments matching
the schema, so there's no prose-wrapping-JSON edge case to parse around
("Here's my analysis: ```json ...```") and no retry-on-malformed-JSON
loop needed. The trade-off is real but worth it here: the model can't
add free-text commentary alongside the structured fields, so anything it
needs to say has to go in the `reasoning` field itself.
"""

SYSTEM_PROMPT = """You are an insurance claims triage assistant for an Australian insurer.

You will be given one claim and a set of policy clauses retrieved as POSSIBLY \
relevant to it. Decide whether the claim is covered, based ONLY on the clauses \
provided - never on general insurance knowledge, and never on a clause you were \
not given.

Rules:
- Cite only clause_ids that were actually provided to you, and only ones that \
materially support your decision. Do not cite a clause just because it was in \
the list.
- If the provided clauses do not clearly address the claim's specific facts \
(e.g. the right peril/exclusion clause doesn't appear in what you were given), \
decide "unsure" rather than guessing - a low-confidence guess is worse than an \
honest "the retrieval didn't surface the right clause."
- "partly_covered" is for cases where a clause itself implies a partial outcome \
(e.g. a sum-insured/underinsurance clause capping payout below the claimed \
amount), not a hedge when you're simply uncertain - use "unsure" for uncertainty.
- confidence must reflect how directly the clauses you cited address this \
claim's specific facts, not how fluent your reasoning sounds. A claim matched \
only by a generic coverage clause with no peril-specific language should score \
LOWER confidence than one matched by a clause naming the exact peril involved.
- reasoning should name which clause(s) drove the decision and why, in 2-4 \
sentences - this is stored as the audit trail for the decision, not a chat reply.
"""


def build_user_message(claim_text: str, policy_type: str, claimant_state: str, amount_claimed: int, prior_claims_count: int, clauses: list[dict]) -> str:
    clause_block = "\n\n".join(
        f"[{c['clause_id']}] ({c['scope']}, {c['jurisdiction']}) {c['heading']}\n{c['text']}" for c in clauses
    )
    return f"""Claim details:
- Policy type: {policy_type}
- Claimant state: {claimant_state}
- Amount claimed: AUD {amount_claimed}
- Claimant's prior claims count: {prior_claims_count}
- Claim text: {claim_text}

Retrieved policy clauses (ranked by retrieval relevance, NOT guaranteed relevant):

{clause_block}

Call submit_triage_decision with your determination."""


TRIAGE_TOOL_SPEC = {
    "toolSpec": {
        "name": "submit_triage_decision",
        "description": "Submit the coverage decision for this claim, based strictly on the provided policy clauses.",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "decision": {
                        "type": "string",
                        "enum": ["covered", "partly_covered", "not_covered", "unsure"],
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "description": "How directly the cited clauses address this claim's specific facts, 0.0-1.0.",
                    },
                    "cited_clause_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "clause_ids from the provided list that materially support the decision. Empty if decision is 'unsure'.",
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "2-4 sentences: which clause(s) drove the decision and why.",
                    },
                },
                "required": ["decision", "confidence", "cited_clause_ids", "reasoning"],
            }
        },
    }
}
