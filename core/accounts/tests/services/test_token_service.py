# accounts/test/services/test_token_service.py
import pytest

from accounts.models import User
from accounts.models.device_session import DeviceSession

from accounts.services.jwt import (
    create_and_store_refresh_token,
)

from accounts.services.token_service import (
    TokenService,
)

@pytest.mark.django_db
def test_rotate_refresh_token():
    user = User.objects.create_user(
        email="token@test.com",
    )

    session = DeviceSession.objects.create(
        user=user,
        device_hash="device",
        ip_address="127.0.0.1",
    )

    refresh = create_and_store_refresh_token(
        user_id=user.id,
        session=session,
    )

    tokens = TokenService.rotate_refresh_token(
        refresh
    )

    assert "access" in tokens
    assert "refresh" in tokens

    assert refresh != tokens["refresh"]