from __future__ import annotations

"""
JWT Authentication — stateless, token-based auth.

How JWT works:
1. Client sends credentials (username/password or API key)
2. Server verifies and returns a signed JWT token
3. Client includes token in every request: Authorization: Bearer <token>
4. Server validates the signature on each request (no DB lookup needed)

Why JWT for healthcare microservices?
- Stateless: no session storage, scales horizontally
- Self-contained: token carries user info (claims)
- Standard: any external system can generate compatible tokens
- Auditable: every request has a known identity

Security rules:
- Tokens expire (default: 60 min)
- Secret key MUST be rotated in production
- Never log tokens
- Use HTTPS in production (tokens are bearer credentials)
"""

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from medscribe.config import Settings, get_settings

# FastAPI security scheme — tells Swagger UI to show a "Bearer token" input
security = HTTPBearer()


class TokenPayload(BaseModel):
    """What's inside the JWT token."""

    sub: str  # Subject — the user/clinician ID
    role: str  # "clinician", "admin", "system"
    exp: datetime  # Expiration time


class AuthenticatedUser(BaseModel):
    """The identity extracted from a valid token. Injected into route handlers."""

    user_id: str
    role: str


def create_access_token(
    user_id: str,
    role: str = "clinician",
    settings: Settings | None = None,
) -> str:
    """
    Create a signed JWT token.

    In production, this would be called by a separate auth service
    or identity provider. For dev/testing, we generate tokens here.
    """
    settings = settings or get_settings()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.access_token_expire_minutes)

    payload = {
        "sub": user_id,
        "role": role,
        "exp": expire,
        "iat": now,  # Issued at
    }

    return jwt.encode(
        payload,
        settings.secret_key.get_secret_value(),
        algorithm="HS256",
    )


def decode_token(token: str, settings: Settings | None = None) -> TokenPayload:
    """Decode and validate a JWT token. Raises on invalid/expired tokens."""
    settings = settings or get_settings()

    try:
        payload = jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            algorithms=["HS256"],
        )
        return TokenPayload(
            sub=payload["sub"],
            role=payload["role"],
            exp=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
        )
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    settings: Settings = Depends(get_settings),
) -> AuthenticatedUser:
    """
    FastAPI dependency — extracts and validates the user from the JWT.

    Usage in routes:
        @router.get("/something")
        async def my_route(user: AuthenticatedUser = Depends(get_current_user)):
            print(user.user_id)  # The authenticated clinician

    This is injected automatically by FastAPI's Depends system.
    """
    token_data = decode_token(credentials.credentials, settings)
    return AuthenticatedUser(user_id=token_data.sub, role=token_data.role)


def require_role(allowed_roles: list[str]):
    """
    Role-based access control (RBAC) dependency.

    Usage:
        @router.post("/admin-only")
        async def admin_route(user: AuthenticatedUser = Depends(require_role(["admin"]))):
            ...

    This checks that the authenticated user has one of the allowed roles.
    """

    async def _check_role(
        user: AuthenticatedUser = Depends(get_current_user),
    ) -> AuthenticatedUser:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' not authorized. Required: {allowed_roles}",
            )
        return user

    return _check_role
