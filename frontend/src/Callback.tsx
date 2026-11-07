import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { handleCallback } from "./auth";

export default function Callback() {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    handleCallback(window.location.search)
      .then(() => navigate("/", { replace: true }))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [navigate]);

  if (error) {
    return (
      <div className="space-y-3">
        <p className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">{error}</p>
        <Link to="/" className="text-sm text-blue-700 hover:underline">
          ← Back to start
        </Link>
      </div>
    );
  }
  return <p className="text-gray-500">Signing you in…</p>;
}
