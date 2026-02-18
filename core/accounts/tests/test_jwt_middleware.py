# accounts/tests/test_jwt_middleware.py
import pytest
from django.urls import reverse

from accounts.models import User
from accounts.services.jwt import create_access_token


@pytest.mark.django_db
def test_jwt_middleware_authenticates_user(client):
    user = User.objects.create_user(
        email="jwt@test.com",
        password="pass123",
    )

    token = create_access_token(user_id=user.id)

    response = client.get(
        "/api/accounts/me/",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert response.status_code == 200
    assert response.json()["email"] == "jwt@test.com"


@pytest.mark.django_db
def test_jwt_middleware_rejects_invalid_token(client):
    response = client.get(
        "/api/accounts/me/",
        HTTP_AUTHORIZATION="Bearer invalid.token.here",
    )

    assert response.status_code == 401
