"""
Claims-metadata tables.

Two tables, deliberately not more:

- `claims`: one row per claim (the synthetic ones from
  data/synthetic/claims/claims.jsonl today, real intake later). Includes
  the eval-only `expected_decision`/`expected_clauses`/`notes` fields from
  generate.py's labelled claims - these are the answer key for measuring
  the agent's accuracy, not something a real production claim would have,
  but keeping them on the same table (rather than a separate "eval set"
  table) means one `claims` row IS the full picture of a labelled test
  case, no join needed to score the agent against it.

- `triage_decisions`: one row per agent RUN against a claim, not one row
  per claim. This is deliberately append-only / insert-only (the app
  should never UPDATE a row here) - that append-only property is what
  makes this table double as the audit log docker-compose.yaml's comment
  mentions, instead of needing a separate audit_log table: "what did the
  agent decide, when, with what reasoning, using which model" is exactly
  an audit trail, and a second table recording the same facts a different
  way would just be duplication to keep in sync.

Not included, on purpose: a separate `policy_clauses` table. Clause text
and its embedding already live in OpenSearch (ingest.py) - that's the
system of record for "what do the clauses say," and this project
deliberately doesn't duplicate it into Postgres. Postgres holds
claims/decisions (relational, transactional data); OpenSearch holds
clauses (search/retrieval data). Mixing the two into one store would mean
keeping them in sync for no real benefit at this scale.

When to change: if claims volume grows past what one Postgres instance
comfortably handles, `triage_decisions` (pure insert, never updated) is
the natural candidate to split off or partition by date first - `claims`
has a much smaller, slower-growing row count.
"""

import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import ARRAY, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# 1024, not a smaller/larger number - matches Titan Text Embeddings V2's
# default output dimension, the same model ingest.py uses for policy
# clauses (see hybrid_search.py's EMBEDDING_DIM). Keeping claims and
# clauses on the same embedding model/dimension is what makes a future
# "find similar past claims" or "find the clause closest to this claim"
# query a plain vector comparison, with nothing to convert between.
EMBEDDING_DIM = 1024


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Claim(Base):
    __tablename__ = "claims"

    # claim_id is the natural key from the synthetic data generator
    # ("CLM-001", ...) and real intake would likely keep a similarly
    # human-referenceable id - used directly as the primary key rather
    # than adding a separate surrogate id column that would just
    # duplicate it, since nothing about this id is expected to change
    # once assigned.
    claim_id: Mapped[str] = mapped_column(String(20), primary_key=True)

    policy_type: Mapped[str] = mapped_column(String(10), nullable=False)
    # Plain String, not a Postgres ENUM type: adding a new policy type
    # later (e.g. "pet") would need an ALTER TYPE migration with an ENUM,
    # versus just inserting a new value with a plain column. Validity is
    # enforced in the application layer (Pydantic/agent code), not the DB
    # schema - the right trade-off for a column whose valid values are
    # still likely to change during active development.

    claimant_state: Mapped[str] = mapped_column(String(10), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    amount_claimed: Mapped[int] = mapped_column(Integer, nullable=False)
    prior_claims_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    is_labelled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # The four fields below are eval-only (see module docstring) - always
    # NULL for a real, non-synthetic claim.
    expected_decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    expected_clauses: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Nullable because it's populated by a separate embedding step after
    # the claim is inserted, not atomically with insertion - the claim
    # exists and is triage-able (via text search / the agent reading it
    # directly) even before its embedding is computed.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # pending -> triaged -> (needs_review | closed), enforced in
    # application logic. Plain String for the same reason as policy_type.

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)

    decisions: Mapped[list["TriageDecision"]] = relationship(back_populates="claim")


class TriageDecision(Base):
    __tablename__ = "triage_decisions"

    # Surrogate UUID primary key here, unlike Claim: there's no natural
    # key for "one run of the agent against one claim" (a claim can be
    # re-triaged, e.g. after a prompt change), so a generated id is the
    # only sensible choice.
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    claim_id: Mapped[str] = mapped_column(String(20), ForeignKey("claims.claim_id"), nullable=False, index=True)

    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    # "covered" | "partly_covered" | "not_covered" | "unsure" - matches
    # generate.py's expected_decision values exactly, so scoring the agent
    # is a direct string comparison against Claim.expected_decision.
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    cited_clause_ids: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)

    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    # Which Bedrock model produced this decision (e.g. a Claude model id/
    # inference profile ARN) - recorded per-row, not assumed globally,
    # because comparing two models' decisions on the same claims later is
    # exactly the kind of eval this field exists to make possible.

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow, index=True)
    # Indexed: the obvious query is "most recent decision for this claim"
    # or "all decisions made today," both of which filter/sort on this.

    claim: Mapped["Claim"] = relationship(back_populates="decisions")
