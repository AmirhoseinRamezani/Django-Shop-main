# tests/services/accounts/test_jwt_service.py
import jwt
import pytest

from django.conf import settings
from django.core.exceptions import ValidationError

from accounts.services.jwt import (
    JWTService,
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
                "user_id": user.id,
            },
            "wrong-secret",
            algorithm="HS256",
        )

        with pytest.raises(ValidationError):

            decode_token(token)

    def test_unknown_type(self):

        token = jwt.encode(
            {
                "type": "abc",
            },
            settings.JWT_ACCESS_SECRET,
            algorithm="HS256",
        )

        with pytest.raises(ValidationError):

            decode_token(token)