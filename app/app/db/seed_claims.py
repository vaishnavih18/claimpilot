"""
One-off loader: data/synthetic/claims/claims.jsonl -> the `claims` table.

Needed because nothing else populates this table yet - migrations only
create the schema. Without this, decide_node's INSERT into
triage_decisions fails on its foreign key the moment you try to run the
agent against ANY claim, since claims.claim_id would have no matching row
for it to reference.

Upserts via ON CONFLICT DO NOTHING on claim_id, not a plain INSERT - safe
to re-run after the generator produces a new/changed batch without
duplicate-key errors on claims already loaded. Deliberately does NOT
update existing rows on conflict: a claim that's already been triaged
shouldn't have its text/amount silently rewritten out from under its
existing decision history in triage_decisions.

Usage:
    python -m app.db.seed_claims
"""

import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.core.paths import find_repo_root
from app.db.base import SessionLocal
from app.db.models import Claim

CLAIMS_FILE = find_repo_root(Path(__file__).resolve().parent) / "data" / "synthetic" / "claims" / "claims.jsonl"


def load_rows() -> list[dict]:
    rows = []
    with open(CLAIMS_FILE) as f:
        for line in f:
            c = json.loads(line)
            rows.append(
                dict(
                    claim_id=c["claim_id"],
                    policy_type=c["policy_type"],
                    claimant_state=c["claimant_state"],
                    text=c["text"],
                    amount_claimed=c["amount_claimed"],
                    prior_claims_count=c["prior_claims_count"],
                    is_labelled=c["is_labelled"],
                    expected_decision=c.get("expected_decision"),
                    expected_clauses=c.get("expected_clauses"),
                    notes=c.get("notes"),
                )
            )
    return rows


def main():
    rows = load_rows()

    session = SessionLocal()
    try:
        # Count before/after rather than trusting the INSERT's rowcount:
        # SQLAlchemy 2.0's "insertmanyvalues" batching for a multi-row
        # ORM-table INSERT ... ON CONFLICT DO NOTHING can report rowcount
        # as -1 (DBAPI's "not available" sentinel) instead of the real
        # count - confirmed by hitting exactly that running this against
        # the test DB, not a hypothetical edge case being guarded against.
        before = session.scalar(select(func.count()).select_from(Claim))

        stmt = insert(Claim).values(rows)
        stmt = stmt.on_conflict_do_nothing(index_elements=["claim_id"])
        session.execute(stmt)

        after = session.scalar(select(func.count()).select_from(Claim))
        session.commit()
        inserted = after - before
    finally:
        session.close()

    print(f"Read {len(rows)} claims from {CLAIMS_FILE}.")
    print(f"Inserted {inserted} new rows ({len(rows) - inserted} already existed, left untouched).")


if __name__ == "__main__":
    main()
