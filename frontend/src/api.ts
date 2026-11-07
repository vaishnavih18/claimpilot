import { clearToken, getToken } from "./auth";
import { config } from "./config";

export type Decision = "covered" | "partly_covered" | "not_covered" | "unsure";

export interface ClaimSummary {
  claim_id: string;
  policy_type: string;
  claimant_state: string;
  amount_claimed: number;
  prior_claims_count: number;
  status: string;
  decision: Decision | "pending";
  confidence: number | null;
}

export interface CitedClause {
  clause_id: string;
  text: string | null;
}

export interface TriageDecision {
  id: string;
  decision: Decision;
  confidence: number | null;
  cited_clauses: CitedClause[];
  reasoning: string;
  model_id: string;
  created_at: string;
}

export interface ClaimDetail {
  claim_id: string;
  policy_type: string;
  claimant_state: string;
  text: string;
  amount_claimed: number;
  prior_claims_count: number;
  status: string;
  created_at: string;
  decision: TriageDecision | null;
}

function backToSignIn(): never {
  clearToken();
  window.location.assign("/");
  throw new Error("Your session has expired. Please sign in again.");
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  if (!token) backToSignIn();
  const res = await fetch(`${config.apiBaseUrl}${path}`, {
    ...init,
    headers: { ...init.headers, Authorization: `Bearer ${token}` },
  });
  if (res.status === 401) backToSignIn();
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json();
}

export const listClaims = () => request<ClaimSummary[]>("/api/claims");
export const getClaim = (id: string) => request<ClaimDetail>(`/api/claims/${encodeURIComponent(id)}`);
export const triageClaim = (id: string) =>
  request<TriageDecision>(`/api/claims/${encodeURIComponent(id)}/triage`, { method: "POST" });
