"""
Cognito ID-token authentication for the API.

A login screen in the frontend protects nothing on its own - anyone can call
the API directly - so every /api/claims* route depends on `get_current_user`
below, which rejects anything that isn't a valid, unexpired Cognito ID token
for THIS user pool and THIS app client.

What is checked on every request:
  - an `Authorization: Bearer <token>` header is present
  - the signature verifies against the user pool's JWKS (fetched from
    https://cognito-idp.<region>.amazonaws.com/<pool>/.well-known/jwks.json
    and cached; PyJWKClient re-fetches when it sees an unknown `kid`, which
    is how Cognito key rotation is picked up)
  - alg is RS256 (the `algorithms` allow-list also blocks alg=none / HS256
    confusion attacks)
  - `iss` is exactly this user pool, `exp` hasn't passed, `aud` is this app
    client's ID
  - `token_use == "id"` (an access token for the same pool is rejected -
    the ID token is the one that carries identity)

Failing closed: any problem (missing header, bad signature, expired, wrong
issuer/audience/token_use, JWKS unreachable) is a 401. If the API itself is
not configured with a pool/client ID, protected routes return 503 rather
than letting requests through. Config is read at request time, not import
time, so /health and app start-up never depend on it.
"""

import os
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# auto_error=False so a missing header is turned into OUR 401 (with a
# WWW-Authenticate header) rather than FastAPI's default 403.
_bearer = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _settings() -> tuple[str, str, str]:
    pool_id = os.environ.get("COGNITO_USER_POOL_ID", "")
    client_id = os.environ.get("COGNITO_APP_CLIENT_ID", "")
    # The region is also embedded in the pool ID ("ap-southeast-2_AbCdEf"),
    # so derive it from there unless explicitly overridden.
    region = os.environ.get("COGNITO_REGION") or (pool_id.split("_")[0] if "_" in pool_id else "")
    if not (pool_id and client_id and region):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured on the server",
        )
    return pool_id, client_id, region


@lru_cache(maxsize=4)
def _jwks_client(jwks_url: str) -> jwt.PyJWKClient:
    # cache_jwk_set: keep the fetched key set for `lifespan` seconds instead
    # of hitting Cognito on every request.
    return jwt.PyJWKClient(jwks_url, cache_jwk_set=True, lifespan=3600)


def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    """FastAPI dependency: returns the verified ID-token claims, or raises 401."""
    pool_id, client_id, region = _settings()

    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise _unauthorized("Missing bearer token")

    issuer = f"https://cognito-idp.{region}.amazonaws.com/{pool_id}"
    try:
        signing_key = _jwks_client(f"{issuer}/.well-known/jwks.json").get_signing_key_from_jwt(credentials.credentials)
        claims = jwt.decode(
            credentials.credentials,
            signing_key.key,
            algorithms=["RS256"],
            issuer=issuer,
            audience=client_id,
            options={"require": ["exp", "iss", "aud", "sub", "token_use"]},
        )
    except jwt.PyJWTError:
        # Covers bad signature, expired, wrong issuer/audience, malformed
        # token, unknown kid, and JWKS fetch failures. The reason is
        # deliberately not echoed back to the caller.
        raise _unauthorized("Invalid or expired token") from None

    if claims.get("token_use") != "id":
        raise _unauthorized("An ID token is required")
    return claims
