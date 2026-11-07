"""initial schema: claims, triage_decisions, pgvector extension

Revision ID: 0001
Revises:
Create Date: 2026-11-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 1024


def upgrade() -> None:
    # Must run before any table uses the Vector column type below - the
    # `vector` extension is what defines that type at the Postgres level.
    # CREATE EXTENSION IF NOT EXISTS, not CREATE EXTENSION bare: this
    # migration might run against a fresh RDS instance (extension not
    # installed yet) or be re-run idempotently in a dev reset - both
    # should succeed without erroring on "extension already exists".
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "claims",
        sa.Column("claim_id", sa.String(20), primary_key=True),
        sa.Column("policy_type", sa.String(10), nullable=False),
        sa.Column("claimant_state", sa.String(10), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("amount_claimed", sa.Integer, nullable=False),
        sa.Column("prior_claims_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_labelled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("expected_decision", sa.String(20), nullable=True),
        sa.Column("expected_clauses", sa.ARRAY(sa.String), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "triage_decisions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("claim_id", sa.String(20), sa.ForeignKey("claims.claim_id"), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("cited_clause_ids", sa.ARRAY(sa.String), nullable=False, server_default="{}"),
        sa.Column("reasoning", sa.Text, nullable=False),
        sa.Column("model_id", sa.String(100), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    # Both indexes support the two queries this table actually gets used
    # for: "every decision for claim X" (claim_id) and "decisions made in
    # the last N minutes/today" (created_at) - see models.py's comment on
    # TriageDecision for why there's no index on `decision` itself (it's a
    # low-cardinality column, a sequential scan over an already-indexed
    # claim_id/created_at slice is cheap enough at this data volume).
    op.create_index("ix_triage_decisions_claim_id", "triage_decisions", ["claim_id"])
    op.create_index("ix_triage_decisions_created_at", "triage_decisions", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_triage_decisions_created_at", table_name="triage_decisions")
    op.drop_index("ix_triage_decisions_claim_id", table_name="triage_decisions")
    op.drop_table("triage_decisions")
    op.drop_table("claims")
    # Deliberately NOT dropping the vector extension here - another
    # database/schema on the same RDS instance (unlikely for this project,
    # but a cheap habit) could depend on it, and DROP EXTENSION would fail
    # loudly anyway if anything still used the type, so there's no real
    # downside to just leaving it installed.
