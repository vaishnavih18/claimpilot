"""
REST endpoints the demo frontend calls (/api/claims...).

Kept in its own router module, included from main.py, so main.py stays the
thin app-setup file it was written to be. /health deliberately stays in
main.py: it must remain dependency-free (see main.py's docstring).

The agent is imported lazily inside the triage endpoint, not at module
load: app.agent.graph pulls in langgraph/psycopg/Bedrock clients, and the
list/detail endpoints (plus /health) shouldn't need any of that to start.
"""

from collections.abc import Iterator
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db.base import SessionLocal
from app.db.models import Claim, TriageDecision

# Every route on this router requires a valid Cognito ID token (app/auth.py).
# /health lives on the app itself in main.py and stays unauthenticated.
router = APIRouter(prefix="/api", dependencies=[Depends(get_current_user)])


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class CitedClause(BaseModel):
    clause_id: str
    # None if the clause text couldn't be fetched (ID not in the index, or
    # OpenSearch unreachable) - the decision itself is still returned.
    text: str | None


class DecisionOut(BaseModel):
    id: str
    decision: str
    confidence: float | None
    cited_clauses: list[CitedClause]
    reasoning: str
    model_id: str
    created_at: datetime


class ClaimSummary(BaseModel):
    claim_id: str
    policy_type: str
    claimant_state: str
    amount_claimed: int
    prior_claims_count: int
    status: str
    # "pending" when the claim has never been triaged.
    decision: str
    confidence: float | None


class ClaimDetail(BaseModel):
    claim_id: str
    policy_type: str
    claimant_state: str
    text: str
    amount_claimed: int
    prior_claims_count: int
    status: str
    created_at: datetime
    decision: DecisionOut | None


def _cited_clauses(clause_ids: list[str]) -> list[CitedClause]:
    """Live OpenSearch lookup of each cited clause's text (no caching - fine
    at this scale). Failures degrade to text=None rather than failing the
    whole request."""
    if not clause_ids:
        return []
    try:
        from app.agent.clients import get_opensearch_client
        from app.agent.retrieval import fetch_clause_texts

        texts = fetch_clause_texts(get_opensearch_client(), clause_ids)
    except Exception:
        texts = {}
    return [CitedClause(clause_id=cid, text=texts.get(cid)) for cid in clause_ids]


def _decision_out(d: TriageDecision) -> DecisionOut:
    return DecisionOut(
        id=str(d.id),
        decision=d.decision,
        confidence=d.confidence,
        cited_clauses=_cited_clauses(list(d.cited_clause_ids or [])),
        reasoning=d.reasoning,
        model_id=d.model_id,
        created_at=d.created_at,
    )


def _latest_decision(db: Session, claim_id: str) -> TriageDecision | None:
    return db.scalars(
        select(TriageDecision)
        .where(TriageDecision.claim_id == claim_id)
        .order_by(TriageDecision.created_at.desc())
        .limit(1)
    ).first()


def _get_claim_or_404(db: Session, claim_id: str) -> Claim:
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id!r} not found")
    return claim


@router.get("/claims", response_model=list[ClaimSummary])
def list_claims(db: Session = Depends(get_db)):
    claims = db.scalars(select(Claim).order_by(Claim.claim_id)).all()

    # Latest decision per claim in one query (DISTINCT ON is Postgres-specific,
    # which is fine - Postgres is the only database this project uses).
    latest = db.scalars(
        select(TriageDecision)
        .distinct(TriageDecision.claim_id)
        .order_by(TriageDecision.claim_id, TriageDecision.created_at.desc())
    ).all()
    latest_by_claim = {d.claim_id: d for d in latest}

    out = []
    for c in claims:
        d = latest_by_claim.get(c.claim_id)
        out.append(
            ClaimSummary(
                claim_id=c.claim_id,
                policy_type=c.policy_type,
                claimant_state=c.claimant_state,
                amount_claimed=c.amount_claimed,
                prior_claims_count=c.prior_claims_count,
                status=c.status,
                decision=d.decision if d else "pending",
                confidence=d.confidence if d else None,
            )
        )
    return out


@router.get("/claims/{claim_id}", response_model=ClaimDetail)
def get_claim(claim_id: str, db: Session = Depends(get_db)):
    claim = _get_claim_or_404(db, claim_id)
    d = _latest_decision(db, claim_id)
    return ClaimDetail(
        claim_id=claim.claim_id,
        policy_type=claim.policy_type,
        claimant_state=claim.claimant_state,
        text=claim.text,
        amount_claimed=claim.amount_claimed,
        prior_claims_count=claim.prior_claims_count,
        status=claim.status,
        created_at=claim.created_at,
        decision=_decision_out(d) if d else None,
    )


# Plain `def`, not `async def`: run_claim is blocking (Bedrock, OpenSearch,
# Postgres), and FastAPI runs sync endpoints in a threadpool so a slow
# triage doesn't block the event loop / other requests.
@router.post("/claims/{claim_id}/triage", response_model=DecisionOut)
def triage_claim(claim_id: str, db: Session = Depends(get_db)):
    claim = _get_claim_or_404(db, claim_id)

    # run_claim takes a claim dict (not an id) - see app/agent/graph.py.
    claim_dict = {
        "claim_id": claim.claim_id,
        "text": claim.text,
        "policy_type": claim.policy_type,
        "claimant_state": claim.claimant_state,
        "amount_claimed": claim.amount_claimed,
        "prior_claims_count": claim.prior_claims_count,
    }

    try:
        from app.agent.graph import run_claim

        result = run_claim(claim_dict)
    except Exception as exc:  # surface agent/Bedrock/OpenSearch failures to the UI
        raise HTTPException(status_code=502, detail=f"Triage failed: {type(exc).__name__}: {exc}") from exc

    # decide_node already persisted the TriageDecision row; read it back.
    db.expire_all()
    d = _latest_decision(db, claim_id)
    if d is None or str(d.id) != result.get("triage_decision_id"):
        raise HTTPException(status_code=500, detail="Triage ran but the decision row could not be found")
    return _decision_out(d)
