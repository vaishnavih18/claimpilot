// Settings come from window.__CLAIMPILOT_CONFIG__ (public/config.js, replaced
// at container start-up in the deployed image) and fall back to VITE_* env
// vars for local dev. None of these are secrets: the Hosted UI domain and
// app client ID are visible in every login redirect.
interface RuntimeConfig {
  apiBaseUrl?: string;
  cognitoDomain?: string;
  cognitoClientId?: string;
  googleLogin?: string | boolean;
}

declare global {
  interface Window {
    __CLAIMPILOT_CONFIG__?: RuntimeConfig;
  }
}

const runtime = window.__CLAIMPILOT_CONFIG__ ?? {};

export const config = {
  // "" means same origin (deployed: the ALB/nginx routes /api to the API).
  // `??` rather than `||` so an explicit "" is respected.
  apiBaseUrl: runtime.apiBaseUrl ?? import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000",
  cognitoDomain: (runtime.cognitoDomain || import.meta.env.VITE_COGNITO_DOMAIN || "").replace(/\/$/, ""),
  cognitoClientId: runtime.cognitoClientId || import.meta.env.VITE_COGNITO_CLIENT_ID || "",
};

// Show "Sign in with Google" (Cognito must have the Google provider enabled,
// i.e. terraform's google_client_id/secret were set).
export const googleLogin = String(runtime.googleLogin ?? import.meta.env.VITE_GOOGLE_LOGIN ?? "") === "true";

export const authConfigured = Boolean(config.cognitoDomain && config.cognitoClientId);
