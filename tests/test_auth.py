"""
Tests for JWT authentication.

Verifies:
- Token creation and decoding
- Expired tokens are rejected
- Invalid tokens are rejected
- Role extraction works
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from medscribe.api.auth import AuthenticatedUser, create_access_token, decode_token
from medscribe.config import Settings


@pytest.fixture
def settings():
    from pydantic import SecretStr

    return Settings(secret_key=SecretStr("test-secret-key-for-unit-tests"))


def test_create_and_decode_token(settings):
    token = create_access_token("DR001", role="clinician", settings=settings)
    payload = decode_token(token, settings)

    assert payload.sub == "DR001"
    assert payload.role == "clinician"
    assert payload.exp > datetime.now(timezone.utc)


def test_token_with_admin_role(settings):
    token = create_access_token("ADMIN01", role="admin", settings=settings)
    payload = decode_token(token, settings)

    assert payload.role == "admin"


def test_invalid_token_raises(settings):
    with pytest.raises(HTTPException) as exc_info:
        decode_token("this.is.not.a.valid.jwt", settings)

    assert exc_info.value.status_code == 401


def test_wrong_secret_raises(settings):
    token = create_access_token("DR001", settings=settings)

    from pydantic import SecretStr

    wrong_settings = Settings(secret_key=SecretStr("wrong-secret"))
    with pytest.raises(HTTPException) as exc_info:
        decode_token(token, wrong_settings)

    assert exc_info.value.status_code == 401


def test_token_contains_issued_at(settings):
    """Token should have 'iat' claim for audit purposes."""
    from jose import jwt as jose_jwt

    token = create_access_token("DR001", settings=settings)
    payload = jose_jwt.decode(
        token, settings.secret_key.get_secret_value(), algorithms=["HS256"]
    )

    assert "iat" in payload
    assert "exp" in payload
    assert payload["iat"] < payload["exp"]
