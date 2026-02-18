# accounts/tests/services/test_jwt_service.py
import pytest
from accounts.models import User
from accounts.services.jwt import create_access_token
from django.core.exceptions import ValidationError


@pytest.mark.django_db
def test_access_token_is_valid():
    user = User.objects.create_user(
        email="jwt@test.com",
        password="pass123",
    )

    token = create_access_token(user_id=user.id)
    assert token is not None
