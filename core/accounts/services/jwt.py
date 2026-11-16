# accounts/services/jwt.py

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import jwt
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounts.models.refresh_token import RefreshToken


ALGORITHM = "HS256"
ACCESS_TOKEN_LIFETIME = timedelta(minutes=15)
REFRESH_TOKEN_LIFETIME = timedelta(days=7)

_REQUIRED_CLAIMS = (
    "exp",
    "iat",
    "jti",
    "type",
    "user_id",
)


def _now():
    return timezone.now()


def create_access_token(*, user_id: int, session_id: str) -> str:
    now = _now()

    payload = {
        "jti": str(uuid.uuid4()),
        "type": "access",
        "user_id": str(user_id),
        "session_id": str(session_id),
        "iat": now,
        "exp": now + ACCESS_TOKEN_LIFETIME,
    }

    return jwt.encode(
        payload,
        settings.JWT_ACCESS_SECRET,
        algorithm=ALGORITHM,
    )


def create_refresh_token(
    *,
    user_id: int,
    session_id: str | None = None,
    family_id: str | None = None,
) -> str:
    now = _now()

    payload = {
        "jti": str(uuid.uuid4()),
        "type": "refresh",
        "user_id": str(user_id),
        "session_id": str(session_id) if session_id else None,
        "family_id": str(family_id) if family_id else None,
        "iat": now,
        "exp": now + REFRESH_TOKEN_LIFETIME,
    }

    return jwt.encode(
        payload,
        settings.JWT_REFRESH_SECRET,
        algorithm=ALGORITHM,
    )


def create_and_store_refresh_token(
    *,
    user_id: int,
    session,
    family_id=None,
) -> str:
    if family_id is None:
        family_id = uuid.uuid4()

    token = create_refresh_token(
        user_id=user_id,
        session_id=session.id,
        family_id=family_id,
    )

    RefreshToken.objects.create(
        user_id=user_id,
        session=session,
        token=token,
        family_id=family_id,
        expires_at=_now() + REFRESH_TOKEN_LIFETIME,
    )

    return token


def _decode_signed_token(
    token: str,
    *,
    secret: str,
    expected_type: str,
) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
            options={
                "require": list(_REQUIRED_CLAIMS),
            },
        )
    except jwt.ExpiredSignatureError as exc:
        raise ValidationError(_("Token expired")) from exc
    except jwt.InvalidTokenError as exc:
        raise ValidationError(_("Invalid token")) from exc

    if payload.get("type") != expected_type:
        raise ValidationError(_("Invalid token type"))

    user_id = payload.get("user_id")
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValidationError(_("Invalid token payload"))

    return payload


def decode_token(token: str) -> dict[str, Any]:
    """
    Decode an access or refresh token using its dedicated signing secret.

    The unverified payload is used only to select the expected token type
    and secret. No claim is trusted until signature verification succeeds.
    """

    if not isinstance(token, str) or not token.strip():
        raise ValidationError(_("Invalid token"))

    try:
        unverified = jwt.decode(
            token,
            options={
                "verify_signature": False,
                "verify_exp": False,
                "verify_iat": False,
                "verify_nbf": False,
            },
            algorithms=[ALGORITHM],
        )
    except jwt.InvalidTokenError as exc:
        raise ValidationError(_("Invalid token")) from exc

    token_type = unverified.get("type")

    if token_type == "access":
        secret = settings.JWT_ACCESS_SECRET
    elif token_type == "refresh":
        secret = settings.JWT_REFRESH_SECRET
    else:
        raise ValidationError(_("Invalid token type"))

    return _decode_signed_token(
        token,
        secret=secret,
        expected_type=token_type,
    )


def decode_access_token(token: str) -> dict[str, Any]:
    return _decode_signed_token(
        token,
        secret=settings.JWT_ACCESS_SECRET,
        expected_type="access",
    )


def decode_refresh_token(token: str) -> dict[str, Any]:
    return _decode_signed_token(
        token,
        secret=settings.JWT_REFRESH_SECRET,
        expected_type="refresh",
    )


class JWTService:
    """High-level JWT service wrapper."""

    @staticmethod
    def create_access_token(user_id: int, session_id: str) -> str:
        return create_access_token(
            user_id=user_id,
            session_id=session_id,
        )

    @staticmethod
    def create_refresh_token(user_id: int, session_id: str) -> str:
        return create_refresh_token(
            user_id=user_id,
            session_id=session_id,
        )

    @staticmethod
    def decode(token: str) -> dict[str, Any]:
        return decode_token(token)