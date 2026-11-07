"""
Eval harness: scores the triage agent against the labelled claims in
data/synthetic/claims/claims.jsonl and diagnoses WHY expected clauses were
not cited. Writes evals/eval-report.md (+ raw evals/eval-results.json).

Usage (from app/, venv active):
    export DATABASE_URL=postgresql+psycopg://claimpilot:claimpilot_local_dev@localhost:5432/claimpilot
    export AWS_PROFILE=claimpilot AWS_REGION=ap-southeast-2
    python ../evals/run_eval.py [--limit N]

How a claim is run: this executes the REAL LangGraph (build_graph() from
app/agent/graph.py, the same nodes and routing as run_claim) but streams it
node by node, so the retrieved clause_ids of try 1 and try 2 can be captured
(retrieve_node overwrites retrieved_clauses on retry, so the final state
alone only shows the last try). Two deliberate differences from run_claim():
  - compiled WITHOUT the Postgres checkpointer, and
  - decide_node's TriageDecision insert is stubbed out,
so eval runs don't add rows to triage_decisions (which the UI reads as the
audit trail) or reuse claim_id as a checkpoint thread_id. The decision
logic itself - including decide_node's "retry + low confidence -> unsure"
override - is the real code.

Miss categories (per expected clause that is not in the final cited_clause_ids):
  corpus_gap            clause_id is not in the policy JSONs or the index
  citation_miss         clause appeared in a try's retrieved set (so the LLM
                        saw it) but was not cited in the final answer
  jurisdiction_filtered clause was never retrieved; its jurisdiction tag
                        excludes it from try 1's filter, and an unfiltered
                        search with try 1's parameters DOES surface it
  retrieval_miss        exists, never retrieved by either try, and not
                        explained by the jurisdiction filter
"""

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "app"))

from app.agent import nodes  # noqa: E402
from app.agent.clients import get_bedrock_runtime_client, get_opensearch_client  # noqa: E402
from app.agent.graph import build_graph  # noqa: E402
from app.agent.retrieval import INDEX_NAME, hybrid_search  # noqa: E402

CLAIMS_FILE = REPO / "data/synthetic/claims/claims.jsonl"
POLICY_DIR = REPO / "data/synthetic/policies"
REPORT = REPO / "evals/eval-report.md"
RAW = REPO / "evals/eval-results.json"


class _NoopSession:
    """Stands in for SessionLocal() inside decide_node so nothing is written."""

    def add(self, row): pass
    def commit(self): pass
    def close(self): pass


def load_corpus() -> dict[str, dict]:
    """clause_id -> {jurisdiction, source}. Union of the raw policy JSONs and
    the OpenSearch index, so a clause missing from either is visible."""
    corpus: dict[str, dict] = {}
    for path in sorted(POLICY_DIR.glob("*.json")):
        for c in json.load(open(path))["clauses"]:
            corpus[c["clause_id"]] = {"jurisdiction": c["jurisdiction"], "in_json": True, "in_index": False}
    os_client = get_opensearch_client()
    resp = os_client.search(index=INDEX_NAME, body={"size": 1000, "_source": ["clause_id", "jurisdiction"], "query": {"match_all": {}}})
    for hit in resp["hits"]["hits"]:
        src = hit["_source"]
        entry = corpus.setdefault(src["clause_id"], {"jurisdiction": src["jurisdiction"], "in_json": False, "in_index": False})
        entry["in_index"] = True
    return corpus


def run_graph(graph, claim: dict) -> dict:
    """Stream the real graph; return final result + per-try retrieved ids."""
    state = {
        "claim_id": claim["claim_id"],
        "claim_text": claim["text"],
        "policy_type": claim["policy_type"],
        "claimant_state": claim["claimant_state"],
        "amount_claimed": claim["amount_claimed"],
        "prior_claims_count": claim["prior_claims_count"],
        "retry_count": 0,
    }
    tries: list[list[str]] = []
    final: dict = dict(state)
    for update in graph.stream(state, stream_mode="updates"):
        for node, delta in update.items():
            final.update(delta or {})
            if node == "retrieve":
                tries.append([c["clause_id"] for c in delta["retrieved_clauses"]])
    return {
        "decision": final["decision"],
        "confidence": final["confidence"],
        "cited": final["cited_clause_ids"],
        "reasoning": final["reasoning"],
        "retries": final.get("retry_count", 0),
        "try1": tries[0] if tries else [],
        "try2": tries[1] if len(tries) > 1 else None,
    }


def run_with_backoff(graph, claim: dict) -> dict:
    for attempt in range(6):
        try:
            return run_graph(graph, claim)
        except Exception as exc:
            if "Throttling" in str(exc) and attempt < 5:
                wait = 15 * (attempt + 1)
                print(f"    throttled, retrying in {wait}s ...", flush=True)
                time.sleep(wait)
                continue
            raise


def categorize(claim: dict, run: dict, corpus: dict, os_client, bedrock) -> list[dict]:
    """One entry per expected clause that was not cited."""
    out = []
    seen = set(run["try1"]) | set(run["try2"] or [])
    for cid in claim["expected_clauses"]:
        if cid in run["cited"]:
            continue
        if cid not in corpus:
            out.append({"clause_id": cid, "category": "corpus_gap", "detail": "not in policy JSONs or OpenSearch index"})
            continue
        if cid in seen:
            where = "try 1" if cid in run["try1"] else "retry only"
            out.append({"clause_id": cid, "category": "citation_miss", "detail": f"retrieved ({where}), not cited"})
            continue
        jur = corpus[cid]["jurisdiction"]
        excluded_by_jurisdiction = jur not in ("national", claim["claimant_state"])
        if excluded_by_jurisdiction:
            # Counterfactual: try 1's exact parameters, jurisdiction filter dropped.
            unfiltered = hybrid_search(os_client, bedrock, claim["text"], k=8, policy_type=claim["policy_type"], jurisdiction=None)
            if cid in {c["clause_id"] for c in unfiltered}:
                note = "surfaces without the filter" + ("; retry ran but did not surface it" if run["retries"] else "; no retry happened")
                out.append({"clause_id": cid, "category": "jurisdiction_filtered", "detail": f"tagged {jur}, claimant in {claim['claimant_state']}; {note}"})
                continue
        suffix = f" (tagged {jur}, excluded for {claim['claimant_state']} but not found unfiltered either)" if excluded_by_jurisdiction else ""
        out.append({"clause_id": cid, "category": "retrieval_miss", "detail": "never in top results of any try" + suffix})
    return out


def write_report(results: list[dict]) -> None:
    ok = [r for r in results if "error" not in r]
    errs = [r for r in results if "error" in r]
    correct = [r for r in ok if r["decision"] == r["expected_decision"]]
    exp_total = sum(len(r["expected_clauses"]) for r in ok)
    exp_cited = sum(len(r["expected_clauses"]) - len(r["misses"]) for r in ok)
    cats = Counter(m["category"] for r in ok for m in r["misses"])
    claims_with_miss = sum(1 for r in ok if r["misses"])

    L = []
    L.append("# ClaimPilot eval report\n")
    L.append(f"Labelled claims: **{len(results)}** &nbsp;·&nbsp; scored: **{len(ok)}** &nbsp;·&nbsp; errored: **{len(errs)}**\n")
    L.append(f"- **Decision accuracy:** {len(correct)}/{len(ok)} = **{len(correct) / max(len(ok), 1):.0%}**")
    L.append(f"- **Expected-clause citation recall:** {exp_cited}/{exp_total} = **{exp_cited / max(exp_total, 1):.0%}** ({claims_with_miss} claims missing at least one)")
    L.append(f"- **Claims that used the retry:** {sum(1 for r in ok if r['retries'])}\n")

    L.append("## Missed expected clauses by cause\n")
    L.append("| Category | Missed clauses |\n|---|---|")
    for c in ("corpus_gap", "retrieval_miss", "jurisdiction_filtered", "citation_miss"):
        L.append(f"| {c} | {cats.get(c, 0)} |")
    L.append(f"| **total** | **{sum(cats.values())}** |\n")

    L.append("## Decisions: expected → actual\n")
    L.append("| Expected | Actual | Count |\n|---|---|---|")
    for (e, a), n in sorted(Counter((r["expected_decision"], r["decision"]) for r in ok).items()):
        L.append(f"| {e} | {a} | {n} |")
    L.append("")

    L.append("## Per claim\n")
    L.append("| Claim | Policy / state | Expected | Actual (conf) | Match | Missed clauses (cause) |\n|---|---|---|---|---|---|")
    for r in results:
        if "error" in r:
            L.append(f"| {r['claim_id']} | {r['policy_type']} / {r['claimant_state']} | {r['expected_decision']} | ERROR | — | {r['error'][:80]} |")
            continue
        match = "✅" if r["decision"] == r["expected_decision"] else "❌"
        misses = "<br>".join(f"{m['clause_id']} — {m['category']}" for m in r["misses"]) or "—"
        L.append(f"| {r['claim_id']} | {r['policy_type']} / {r['claimant_state']} | {r['expected_decision']} | {r['decision']} ({r['confidence']:.2f}) | {match} | {misses} |")
    L.append("")

    L.append("## Miss details\n")
    for r in ok:
        for m in r["misses"]:
            L.append(f"- **{r['claim_id']}** {m['clause_id']} — `{m['category']}`: {m['detail']}")
    L.append("")
    REPORT.write_text("\n".join(L))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    nodes.SessionLocal = _NoopSession  # decide_node must not write during evals

    claims = [json.loads(l) for l in open(CLAIMS_FILE)]
    claims = [c for c in claims if c.get("is_labelled")]
    if args.limit:
        claims = claims[: args.limit]

    graph = build_graph().compile()
    corpus = load_corpus()
    os_client, bedrock = get_opensearch_client(), get_bedrock_runtime_client()
    print(f"Corpus: {len(corpus)} clauses. Running {len(claims)} labelled claims.\n", flush=True)

    results = []
    for i, claim in enumerate(claims, 1):
        base = {k: claim[k] for k in ("claim_id", "policy_type", "claimant_state", "expected_decision", "expected_clauses")}
        try:
            run = run_with_backoff(graph, claim)
            misses = categorize(claim, run, corpus, os_client, bedrock)
            r = {**base, **run, "misses": misses}
            flag = "OK  " if r["decision"] == r["expected_decision"] else "MISS"
            print(f"[{i}/{len(claims)}] {claim['claim_id']} {flag} expected={r['expected_decision']} got={r['decision']} ({r['confidence']:.2f}) "
                  f"retries={r['retries']} missed_clauses={[m['clause_id'] + ':' + m['category'] for m in misses]}", flush=True)
        except Exception as exc:
            r = {**base, "error": f"{type(exc).__name__}: {exc}"}
            print(f"[{i}/{len(claims)}] {claim['claim_id']} ERROR {r['error'][:120]}", flush=True)
        results.append(r)
        RAW.write_text(json.dumps(results, indent=2))

    write_report(results)
    print(f"\nWrote {REPORT}")


if __name__ == "__main__":
    main()
