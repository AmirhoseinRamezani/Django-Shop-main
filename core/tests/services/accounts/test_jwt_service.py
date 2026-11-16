# tests/services/accounts/test_jwt_service.py

import jwt
import pytest

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.services.jwt import (
    ALGORITHM,
    JWTService,
    decode_access_token,
    decode_refresh_token,
    decode_token,
)


pytestmark = pytest.mark.django_db


class TestCreateAccessToken:

    def test_create(self, user, device_session):
        token = JWTService.create_access_token(
            user.id,
            str(device_session.id),
        )

        payload = decode_token(token)

        assert payload["type"] == "access"
        assert payload["user_id"] == str(user.id)
        assert payload["session_id"] == str(device_session.id)

    def test_contains_jti(self, user, device_session):
        token = JWTService.create_access_token(
            user.id,
            str(device_session.id),
        )

        payload = decode_token(token)

        assert payload["jti"]

    def test_contains_exp(self, user, device_session):
        token = JWTService.create_access_token(
            user.id,
            str(device_session.id),
        )

        payload = decode_token(token)

        assert payload["exp"] > payload["iat"]


class TestCreateRefreshToken:

    def test_create(self, user, device_session):
        token = JWTService.create_refresh_token(
            user.id,
            str(device_session.id),
        )

        payload = decode_token(token)

        assert payload["type"] == "refresh"

    def test_family_id(self, user, device_session):
        token = JWTService.create_refresh_token(
            user.id,
            str(device_session.id),
        )

        payload = decode_token(token)

        assert "family_id" in payload


class TestDecode:

    def test_invalid_token(self):
        with pytest.raises(ValidationError):
            decode_token("invalid-token")

    def test_invalid_signature(self, user, device_session):
        token = jwt.encode(
            {
                "type": "access",
                "user_id": str(user.id),
                "session_id": str(device_session.id),
                "jti": "test-jti",
                "iat": timezone.now(),
                "exp": timezone.now() + timezone.timedelta(minutes=5),
            },
            "wrong-secret-with-at-least-thirty-two-bytes",
            algorithm=ALGORITHM,
        )

        with pytest.raises(ValidationError):
            decode_token(token)

    def test_unknown_type(self):
        token = jwt.encode(
            {
                "type": "unknown",
                "user_id": "1",
                "jti": "test-jti",
                "iat": timezone.now(),
                "exp": timezone.now() + timezone.timedelta(minutes=5),
            },
            settings.JWT_ACCESS_SECRET,
            algorithm=ALGORITHM,
        )

        with pytest.raises(ValidationError):
            decode_token(token)

    @pytest.mark.parametrize(
        "missing_claim",
        ("exp", "iat", "jti", "type", "user_id"),
    )
    def test_required_claims_are_enforced(
        self,
        missing_claim,
        user,
        device_session,
    ):
        payload = {
            "type": "access",
            "user_id": str(user.pk),
            "session_id": str(device_session.pk),
            "jti": "test-jti",
            "iat": timezone.now(),
            "exp": timezone.now() + timezone.timedelta(minutes=5),
        }
        payload.pop(missing_claim)

        token = jwt.encode(
            payload,
            settings.JWT_ACCESS_SECRET,
            algorithm=ALGORITHM,
        )

        with pytest.raises(ValidationError):
            decode_token(token)

    def test_access_decoder_rejects_refresh_token(
        self,
        user,
        device_session,
    ):
        token = JWTService.create_refresh_token(
            user.id,
            str(device_session.id),
        )

        with pytest.raises(ValidationError):
            decode_access_token(token)

    def test_refresh_decoder_rejects_access_token(
        self,
        user,
        device_session,
    ):
        token = JWTService.create_access_token(
            user.id,
            str(device_session.id),
        )

        with pytest.raises(ValidationError):
            decode_refresh_token(token)