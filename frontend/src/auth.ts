// Cognito Hosted UI sign-in: Authorization Code flow with PKCE (public
// client, no secret). The ID token lives in sessionStorage - cleared when
// the tab closes, and not shared across tabs/sessions like localStorage.
import { authConfigured, config } from "./config";

const TOKEN_KEY = "claimpilot.id_token";
const VERIFIER_KEY = "claimpilot.pkce_verifier";
const STATE_KEY = "claimpilot.oauth_state";

const redirectUri = () => `${window.location.origin}/callback`;

function base64url(bytes: Uint8Array): string {
  let s = "";
  bytes.forEach((b) => (s += String.fromCharCode(b)));
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function randomString(byteLength = 48): string {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  return base64url(bytes);
}

async function sha256(text: string): Promise<Uint8Array> {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)));
}

interface IdClaims {
  exp: number;
  email?: string;
}

function decodeClaims(token: string): IdClaims | null {
  try {
    const payload = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(atob(payload.padEnd(Math.ceil(payload.length / 4) * 4, "=")));
  } catch {
    return null;
  }
}

// The signature is verified by the API on every call; here we only read
// `exp` so an expired token sends the user back to sign-in instead of
// showing an app whose every request will 401.
export function getToken(): string | null {
  let token: string | null = null;
  try {
    token = sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
  if (!token) return null;
  const claims = decodeClaims(token);
  if (!claims || claims.exp * 1000 <= Date.now() + 30_000) {
    clearToken();
    return null;
  }
  return token;
}

export function getEmail(): string | null {
  const token = getToken();
  return token ? decodeClaims(token)?.email ?? null : null;
}

export function clearToken(): void {
  try {
    sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable */
  }
}

// provider "Google" skips Cognito's chooser and goes straight to Google;
// omit it for the Hosted UI (email + password, plus any provider buttons).
export async function startLogin(provider?: "Google"): Promise<void> {
  if (!authConfigured) throw new Error("Sign-in is not configured (missing Cognito domain / client ID).");
  if (!window.crypto?.subtle) {
    // crypto.subtle only exists in secure contexts: https:// or localhost.
    throw new Error("Sign-in needs a secure context. Open the app over https:// or at http://localhost.");
  }
  const verifier = randomString(64);
  const state = randomString(16);
  sessionStorage.setItem(VERIFIER_KEY, verifier);
  sessionStorage.setItem(STATE_KEY, state);

  const params = new URLSearchParams({
    response_type: "code",
    client_id: config.cognitoClientId,
    redirect_uri: redirectUri(),
    scope: "openid email profile",
    code_challenge: base64url(await sha256(verifier)),
    code_challenge_method: "S256",
    state,
  });
  if (provider) params.set("identity_provider", provider);
  window.location.assign(`${config.cognitoDomain}/oauth2/authorize?${params}`);
}

// A code can only be exchanged once; React StrictMode runs effects twice in
// dev, so share one in-flight promise per code.
let inFlight: { code: string; promise: Promise<void> } | null = null;

export function handleCallback(search: string): Promise<void> {
  const params = new URLSearchParams(search);
  const code = params.get("code");
  if (inFlight && inFlight.code === code) return inFlight.promise;
  const promise = exchange(params);
  if (code) inFlight = { code, promise };
  return promise;
}

async function exchange(params: URLSearchParams): Promise<void> {
  const error = params.get("error");
  if (error) throw new Error(params.get("error_description") || error);

  const code = params.get("code");
  const expectedState = sessionStorage.getItem(STATE_KEY);
  const verifier = sessionStorage.getItem(VERIFIER_KEY);
  if (!code || !verifier || !expectedState || params.get("state") !== expectedState) {
    throw new Error("Sign-in response did not match the request. Please try signing in again.");
  }

  const res = await fetch(`${config.cognitoDomain}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      client_id: config.cognitoClientId,
      code,
      redirect_uri: redirectUri(),
      code_verifier: verifier,
    }),
  });
  if (!res.ok) throw new Error("Could not complete sign-in. Please try again.");
  const tokens = await res.json();
  if (!tokens.id_token) throw new Error("Sign-in response had no ID token.");

  sessionStorage.setItem(TOKEN_KEY, tokens.id_token);
  sessionStorage.removeItem(VERIFIER_KEY);
  sessionStorage.removeItem(STATE_KEY);
}

export function logout(): void {
  clearToken();
  if (!authConfigured) {
    window.location.assign("/");
    return;
  }
  const params = new URLSearchParams({ client_id: config.cognitoClientId, logout_uri: `${window.location.origin}/` });
  window.location.assign(`${config.cognitoDomain}/logout?${params}`);
}
