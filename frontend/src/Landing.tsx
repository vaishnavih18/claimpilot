import { useState } from "react";
import { startLogin } from "./auth";
import { googleLogin } from "./config";

export default function Landing() {
  const [error, setError] = useState<string | null>(null);

  async function signIn(provider?: "Google") {
    setError(null);
    try {
      await startLogin(provider);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="mx-auto max-w-2xl py-10">
      <h1 className="text-4xl font-bold">ClaimPilot</h1>
      <p className="mt-4 text-lg text-gray-700">
        An agentic insurance-claims triage assistant. Given a claim and the policy it falls under, an agent retrieves
        the relevant policy clauses, reasons over them with an LLM, and returns a decision — <strong>covered</strong>,{" "}
        <strong>partly covered</strong>, <strong>not covered</strong> or <strong>unsure</strong> — with the cited
        clauses and a confidence score.
      </p>

      <h2 className="mt-8 text-sm font-semibold uppercase tracking-wide text-gray-500">What's under the hood</h2>
      <p className="mt-2 text-gray-700">
        The agent is orchestrated with LangGraph (retrieve → assess → retry once if unsure → decide) and runs on AWS:
        EKS for the API and this frontend, RDS Postgres for claims and decisions, OpenSearch for hybrid
        (keyword + vector) clause search, Bedrock for the Claude model, and Google sign-in through Amazon Cognito. All claims and
        policies are synthetic.
      </p>

      <div className="mt-8 flex flex-wrap items-center gap-4">
        <button
          onClick={() => signIn(googleLogin ? "Google" : undefined)}
          className="rounded bg-blue-700 px-6 py-2.5 font-medium text-white hover:bg-blue-800"
        >
          {googleLogin ? "Sign in with Google" : "Sign In"}
        </button>
        {googleLogin && (
          <button onClick={() => signIn()} className="text-sm text-blue-700 hover:underline">
            Use email and password instead
          </button>
        )}
      </div>
      {error && <p className="mt-4 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">{error}</p>}
    </div>
  );
}
