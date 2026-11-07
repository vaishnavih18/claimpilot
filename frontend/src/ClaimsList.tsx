import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ClaimSummary, listClaims } from "./api";
import Badge from "./Badge";

export default function ClaimsList() {
  const [claims, setClaims] = useState<ClaimSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    listClaims().then(setClaims).catch((e) => setError(e.message));
  }, []);

  if (error) return <p className="text-red-700">Failed to load claims: {error}</p>;
  if (!claims) return <p className="text-gray-500">Loading claims…</p>;
  if (claims.length === 0) return <p className="text-gray-500">No claims found.</p>;

  return (
    <table className="w-full text-left text-sm">
      <thead className="border-b text-gray-500">
        <tr>
          <th className="py-2">Claim</th>
          <th>Policy</th>
          <th>State</th>
          <th className="text-right">Amount</th>
          <th className="text-right">Prior claims</th>
          <th className="pl-6">Status</th>
          <th className="text-right">Confidence</th>
        </tr>
      </thead>
      <tbody>
        {claims.map((c) => (
          <tr
            key={c.claim_id}
            onClick={() => navigate(`/claims/${c.claim_id}`)}
            className="cursor-pointer border-b hover:bg-gray-50"
          >
            <td className="py-2 font-medium">{c.claim_id}</td>
            <td className="capitalize">{c.policy_type}</td>
            <td>{c.claimant_state}</td>
            <td className="text-right">${c.amount_claimed.toLocaleString()}</td>
            <td className="text-right">{c.prior_claims_count}</td>
            <td className="pl-6">
              <Badge decision={c.decision} />
            </td>
            <td className="text-right">{c.confidence != null ? `${Math.round(c.confidence * 100)}%` : "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
