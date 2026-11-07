import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ClaimDetail as Claim, getClaim, triageClaim } from "./api";
import Badge from "./Badge";

export default function ClaimDetail() {
  const { claimId = "" } = useParams();
  const [claim, setClaim] = useState<Claim | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [triageError, setTriageError] = useState<string | null>(null);

  useEffect(() => {
    getClaim(claimId).then(setClaim).catch((e) => setLoadError(e.message));
  }, [claimId]);

  async function runTriage() {
    setRunning(true);
    setTriageError(null);
    try {
      const decision = await triageClaim(claimId);
      setClaim((c) => (c ? { ...c, decision } : c));
    } catch (e) {
      setTriageError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  }

  if (loadError) return <p className="text-red-700">Failed to load claim: {loadError}</p>;
  if (!claim) return <p className="text-gray-500">Loading…</p>;

  const d = claim.decision;
  return (
    <div className="space-y-6">
      <Link to="/" className="text-sm text-blue-700 hover:underline">
        ← All claims
      </Link>

      <section>
        <h2 className="text-xl font-semibold">{claim.claim_id}</h2>
        <dl className="mt-3 grid grid-cols-2 gap-x-8 gap-y-2 text-sm sm:grid-cols-4">
          <div><dt className="text-gray-500">Policy</dt><dd className="capitalize">{claim.policy_type}</dd></div>
          <div><dt className="text-gray-500">State</dt><dd>{claim.claimant_state}</dd></div>
          <div><dt className="text-gray-500">Amount claimed</dt><dd>${claim.amount_claimed.toLocaleString()}</dd></div>
          <div><dt className="text-gray-500">Prior claims</dt><dd>{claim.prior_claims_count}</dd></div>
        </dl>
        <p className="mt-4 rounded border bg-gray-50 p-3 text-sm">{claim.text}</p>
      </section>

      <section className="space-y-3">
        <div className="flex items-center gap-3">
          <button
            onClick={runTriage}
            disabled={running}
            className="rounded bg-blue-700 px-4 py-2 text-sm font-medium text-white hover:bg-blue-800 disabled:opacity-50"
          >
            {running ? "Running triage…" : d ? "Re-run triage" : "Run triage"}
          </button>
          {running && <span className="text-sm text-gray-500">Calling the agent — this can take several seconds.</span>}
        </div>

        {triageError && (
          <p className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">Triage failed — {triageError}</p>
        )}

        {d && (
          <div className={`space-y-3 rounded border p-4 ${running ? "opacity-50" : ""}`}>
            <div className="flex items-center gap-3">
              <Badge decision={d.decision} />
              <span className="text-sm text-gray-600">
                Confidence: {d.confidence != null ? `${Math.round(d.confidence * 100)}%` : "—"}
              </span>
            </div>
            <div>
              <h3 className="text-sm font-medium text-gray-500">Cited clauses</h3>
              {d.cited_clauses.length ? (
                <ul className="mt-1 space-y-3">
                  {d.cited_clauses.map((c) => (
                    <li key={c.clause_id}>
                      <div className="text-sm font-medium">{c.clause_id}</div>
                      <blockquote className="mt-1 border-l-4 border-blue-300 bg-blue-50 px-3 py-2 text-sm italic text-gray-700">
                        {c.text ?? "Clause text unavailable."}
                      </blockquote>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-gray-500">None</p>
              )}
            </div>
            <div>
              <h3 className="text-sm font-medium text-gray-500">Reasoning</h3>
              <p className="whitespace-pre-wrap text-sm">{d.reasoning}</p>
            </div>
            <p className="text-xs text-gray-400">
              {new Date(d.created_at).toLocaleString()} · {d.model_id}
            </p>
          </div>
        )}
      </section>
    </div>
  );
}
