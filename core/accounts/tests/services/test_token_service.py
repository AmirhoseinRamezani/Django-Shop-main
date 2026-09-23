# accounts/test/services/test_token_service.py
import pytest
from django.core.exceptions import ValidationError

from accounts.models import User
from accounts.models.device_session import DeviceSession
from accounts.models.refresh_token import RefreshToken

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

@pytest.mark.django_db
def test_refresh_token_rejected_after_session_revocation():
    user = User.objects.create_user(email="revoked-token@test.com")
    session = DeviceSession.objects.create(
        user=user,
        device_hash="device",
        ip_address="127.0.0.1",
    )
    refresh = create_and_store_refresh_token(user_id=user.id, session=session)

    session.revoke()

    with pytest.raises(ValidationError, match="Session revoked"):
        TokenService.rotate_refresh_token(refresh)


@pytest.mark.django_db
def test_refresh_token_family_binding_is_enforced():
    user = User.objects.create_user(email="family-token@test.com")
    session = DeviceSession.objects.create(
        user=user,
        device_hash="device",
        ip_address="127.0.0.1",
    )
    refresh = create_and_store_refresh_token(user_id=user.id, session=session)
    token_obj = RefreshToken.objects.get(token=refresh)
    token_obj.family_id = __import__("uuid").uuid4()
    token_obj.save(update_fields=["family_id"])

    with pytest.raises(ValidationError, match="Token family mismatch"):
        TokenService.rotate_refresh_token(refresh)
