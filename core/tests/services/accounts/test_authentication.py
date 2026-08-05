# tests/services/accounts/test_authentication.py
import pytest

from rest_framework.test import APIRequestFactory
from rest_framework.exceptions import AuthenticationFailed

from accounts.authentication import JWTAuthentication
from accounts.services.jwt import JWTService

pytestmark = pytest.mark.django_db


class TestAuthentication:

    def test_success(
        self,
        user,
        device_session,
    ):

        token = JWTService.create_access_token(
            user.id,
            str(device_session.id),
        )

        factory = APIRequestFactory()

        request = factory.get(
            "/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        auth = JWTAuthentication()

        authenticated, _ = auth.authenticate(request)

        assert authenticated == user

    def test_missing_header(self):

        factory = APIRequestFactory()

        request = factory.get("/")

        auth = JWTAuthentication()

        assert auth.authenticate(request) is None

    def test_invalid_header(self):

        factory = APIRequestFactory()

        request = factory.get(
            "/",
            HTTP_AUTHORIZATION="Token abc",
        )

        auth = JWTAuthentication()

        with pytest.raises(AuthenticationFailed):

            auth.authenticate(request)

    def test_invalid_token(self):

        factory = APIRequestFactory()

        request = factory.get(
            "/",
            HTTP_AUTHORIZATION="Bearer invalid",
        )

        auth = JWTAuthentication()

        with pytest.raises(AuthenticationFailed):

            auth.authenticate(request)

    def test_inactive_session(
        self,
        user,
        device_session,
    ):

        device_session.is_active = False
        device_session.save()

        token = JWTService.create_access_token(
            user.id,
            str(device_session.id),
        )

        factory = APIRequestFactory()

        request = factory.get(
            "/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        auth = JWTAuthentication()

        with pytest.raises(AuthenticationFailed):

            auth.authenticate(request)