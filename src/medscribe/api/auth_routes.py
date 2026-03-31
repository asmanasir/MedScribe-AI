"""
Authentication routes — token generation.

In production, you'd integrate with:
- Azure AD / Entra ID (enterprise SSO)
- HelseID (Norwegian healthcare identity)
- Your own user database

For now, we have a simple API-key based token endpoint
that's suitable for dev/testing and service-to-service auth.
"""

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status

from medscribe.api.auth import create_access_token
from medscribe.config import Settings, get_settings

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


class TokenRequest(BaseModel):
    """Request body for token generation."""

    client_id: str = Field(min_length=1, description="Service or user identifier")
    client_secret: str = Field(min_length=1, description="API key or password")
    role: str = Field(default="clinician", description="Requested role")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


@router.post("/token", response_model=TokenResponse)
async def get_token(
    request: TokenRequest,
    settings: Settings = Depends(get_settings),
):
    """
    Exchange credentials for a JWT token.

    In production, this validates against a user store or
    identity provider. For dev, we accept any client_id
    with the correct API secret.

    The EPJ system would call this endpoint first, then use the returned
    token for all subsequent API calls.
    """
    # DEV: simple secret check. PROD: replace with real auth.
    expected_secret = settings.secret_key.get_secret_value()
    if request.client_secret != expected_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    token = create_access_token(
        user_id=request.client_id,
        role=request.role,
        settings=settings,
    )

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
    )
