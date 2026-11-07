import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { getEmail, getToken, logout } from "./auth";
import Callback from "./Callback";
import ClaimDetail from "./ClaimDetail";
import ClaimsList from "./ClaimsList";
import Landing from "./Landing";

// Signed-in visitors skip the landing page and go straight to the claims
// list; signed-out visitors see the landing page at "/" and are only sent
// to Cognito when they click Sign In.
function Home() {
  return getToken() ? <ClaimsList /> : <Landing />;
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  return getToken() ? <>{children}</> : <Navigate to="/" replace />;
}

export default function App() {
  useLocation(); // re-render on navigation so the header reflects sign-in/sign-out
  const email = getEmail();
  return (
    <div className="mx-auto max-w-5xl p-6">
      <header className="mb-6 flex items-center justify-between border-b pb-3">
        <div>
          <Link to="/" className="text-2xl font-bold">ClaimPilot</Link>
          <span className="ml-3 text-sm text-gray-500">claims triage demo</span>
        </div>
        {email && (
          <div className="flex items-center gap-3 text-sm">
            <span className="text-gray-600">{email}</span>
            <button onClick={logout} className="rounded border px-3 py-1 hover:bg-gray-50">
              Sign out
            </button>
          </div>
        )}
      </header>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/callback" element={<Callback />} />
        <Route path="/claims/:claimId" element={<RequireAuth><ClaimDetail /></RequireAuth>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  );
}
