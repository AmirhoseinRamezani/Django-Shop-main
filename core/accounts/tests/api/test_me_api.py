# accounts/tests/api/test_me_api.py
import pytest
from accounts.models import User
from accounts.services.jwt import create_access_token


@pytest.mark.django_db
def test_jwt_middleware_authenticates_user(client):
    user = User.objects.create_user(
        email="jwt@test.com",
        password="pass123",
    )

    token = create_access_token(user_id=user.id)

    resp = client.get(
        "/api/accounts/me/",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert resp.status_code == 200
    assert resp.json()["email"] == "jwt@test.com"
