"""
Tests for app/auth.py with a locally generated RSA key standing in for
Cognito's JWKS - no AWS access or network needed, so it runs in CI.

Checks that the dependency accepts one good ID token and rejects every kind
of bad one (fail closed), and that every /api route in the real app actually
carries the dependency while /health does not.

Usage (from app/):  python scripts/test_auth.py
"""

import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# The real app imports app.db.base, which builds an engine at import time.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://x:y@localhost:5432/x")

import jwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from fastapi import Depends, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.auth as auth  # noqa: E402

POOL = "ap-southeast-2_TestPool1"
CLIENT = "testclientid123"
ISS = f"https://cognito-idp.ap-southeast-2.amazonaws.com/{POOL}"
os.environ["COGNITO_USER_POOL_ID"] = POOL
os.environ["COGNITO_APP_CLIENT_ID"] = CLIENT

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeJWKS:
    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=KEY.public_key())


auth._jwks_client = lambda url: FakeJWKS()

probe = FastAPI()


@probe.get("/probe")
def _probe(user: dict = Depends(auth.get_current_user)):
    return {"sub": user["sub"]}


client = TestClient(probe)


def token(key=KEY, **over):
    now = int(time.time())
    claims = {"sub": "user-1", "iss": ISS, "aud": CLIENT, "token_use": "id", "iat": now, "exp": now + 600, "email": "a@b.co"}
    claims.update(over)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k1"})


def call(tok=None, header=None):
    headers = {"Authorization": header} if header else ({"Authorization": f"Bearer {tok}"} if tok else {})
    return client.get("/probe", headers=headers).status_code


failures = []


def expect(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}: {got}" + ("" if ok else f" (wanted {want})"))
    if not ok:
        failures.append(name)


print("dependency behaviour:")
expect("valid id token", call(token()), 200)
expect("no Authorization header", call(), 401)
expect("non-bearer scheme", call(header="Basic abc"), 401)
expect("garbage token", call("not.a.jwt"), 401)
expect("expired token", call(token(exp=int(time.time()) - 60)), 401)
expect("wrong audience (other app client)", call(token(aud="someotherclient")), 401)
expect("wrong issuer (other user pool)", call(token(iss="https://cognito-idp.ap-southeast-2.amazonaws.com/ap-southeast-2_Evil")), 401)
expect("access token instead of id token", call(token(token_use="access")), 401)
expect("missing token_use claim", call(token(token_use=None)), 401)
expect("signed with a different key", call(token(key=OTHER_KEY)), 401)
expect("alg=none unsigned token", call(jwt.encode({"sub": "x", "iss": ISS, "aud": CLIENT, "token_use": "id", "exp": int(time.time()) + 600}, None, algorithm="none")), 401)
expect("HS256 token (algorithm confusion)", call(jwt.encode({"sub": "x", "iss": ISS, "aud": CLIENT, "token_use": "id", "exp": int(time.time()) + 600}, "secret", algorithm="HS256")), 401)

saved = os.environ.pop("COGNITO_APP_CLIENT_ID")
expect("server not configured -> closed (503), not open", call(token()), 503)
os.environ["COGNITO_APP_CLIENT_ID"] = saved

print("real app wiring:")
from app.main import app  # noqa: E402

api_routes = [r for r in app.routes if getattr(r, "path", "").startswith("/api")]
expect("found /api routes", len(api_routes) >= 3, True)
unprotected = [r.path for r in api_routes if not any(d.call is auth.get_current_user for d in r.dependant.dependencies)]
expect("every /api route requires auth", unprotected, [])

real = TestClient(app)
expect("GET /health without token", real.get("/health").status_code, 200)
for method, path in (("get", "/api/claims"), ("get", "/api/claims/CLM-001"), ("post", "/api/claims/CLM-001/triage")):
    expect(f"{method.upper()} {path} without token", getattr(real, method)(path).status_code, 401)
expect("OPTIONS preflight still answered (CORS)", real.options("/api/claims", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"}).status_code, 200)

print()
if failures:
    print(f"{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("all auth tests passed")
