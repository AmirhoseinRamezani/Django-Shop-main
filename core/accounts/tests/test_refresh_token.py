# accounts/test/test_refresh_token.py
import pytest
from accounts.services.jwt import create_refresh_token
from accounts.models import User


@pytest.mark.django_db
def test_refresh_token_works(client):
    user = User.objects.create_user(
        email="refresh@test.com",
        password="pass123"
    )

    refresh = create_refresh_token(user_id=user.id)

    resp = client.get(
        "/api/accounts/me/",
        HTTP_AUTHORIZATION=f"Bearer {refresh}",
    )

    assert resp.status_code == 401
