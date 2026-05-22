import httpx
from jose import jwt as jose_jwt, JWTError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config import get_settings

settings = get_settings()
_bearer = HTTPBearer()


class _CognitoValidator:
    """
    Validates Cognito id_tokens using the pool's public JWKS keys (RS256).
    Keys are fetched lazily on first use and refreshed on cache miss
    to handle Cognito key rotation transparently.
    """

    def __init__(self):
        # Fix #2: use the computed property, not the raw empty-string field
        self._jwks_url = f"{settings.cognito_authority}/.well-known/jwks.json"
        self._issuer   = settings.cognito_authority
        self._keys: dict[str, dict] = {}
        print(f"[auth] Validator initialised — issuer={self._issuer}")

    def _load_keys(self) -> None:
        resp = httpx.get(self._jwks_url, timeout=10)
        resp.raise_for_status()
        self._keys = {k["kid"]: k for k in resp.json()["keys"]}
        print(f"[auth] Loaded {len(self._keys)} JWKS keys from Cognito")

    def decode(self, token: str) -> dict:
        headers = jose_jwt.get_unverified_headers(token)
        claims  = jose_jwt.get_unverified_claims(token)

        kid = headers.get("kid", "")
        if kid not in self._keys:
            self._load_keys()
        if kid not in self._keys:
            raise JWTError(f"Unknown signing key: {kid}")

        # Fix #1: validate aud against the full client allowlist, not a single non-existent field
        aud = claims.get("aud")
        if aud not in settings.allowed_client_ids:
            raise JWTError(f"Token audience '{aud}' is not a registered client")

        return jose_jwt.decode(
            token,
            self._keys[kid],
            algorithms=["RS256"],
            audience=aud,
            issuer=self._issuer,
        )


_validator = _CognitoValidator()


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(_bearer)) -> dict:
    """Validate a Cognito id_token and return its claims as the current user."""  # Fix #7: docstring first
    token = credentials.credentials
    try:
        return _validator.decode(token)
    except Exception as e:
        print(f"[auth] Token validation failed — {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_role(*roles: str):
    """
    Dependency: raises 403 if the user's role doesn't match.
    Checks both custom:role claim (set at registration) and cognito:groups.
    """
    async def checker(current_user: dict = Depends(get_current_user)):
        user_role: str = current_user.get("custom:role", "")
        user_groups: list[str] = current_user.get("cognito:groups", [])
        if user_role not in roles and not any(r in user_groups for r in roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access restricted to roles: {', '.join(roles)}",
            )
        return current_user
    return checker
