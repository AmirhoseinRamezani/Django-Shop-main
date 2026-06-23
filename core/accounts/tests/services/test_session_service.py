# accounts/test/services/test_session_service.py
import pytest

from accounts.models import (
    User,
    DeviceSession,
    RefreshToken,
)

from accounts.services.session_service import SessionService


@pytest.mark.django_db
def test_revoke_session():
    user = User.objects.create_user(
        email="user@test.com",
    )

    session = DeviceSession.objects.create(
        user=user,
        device_hash="device",
        ip_address="127.0.0.1",
    )

    RefreshToken.objects.create(
        user=user,
        session=session,
        token="token",
    )

    SessionService.revoke_session(session)

    session.refresh_from_db()

    assert session.is_active is False

    assert RefreshToken.objects.filter(
        session=session,
        is_revoked=True,
    ).exists()


@pytest.mark.django_db
def test_logout_all():
    user = User.objects.create_user(
        email="user@test.com",
    )

    s1 = DeviceSession.objects.create(
        user=user,
        device_hash="1",
        ip_address="127.0.0.1",
    )

    s2 = DeviceSession.objects.create(
        user=user,
        device_hash="2",
        ip_address="127.0.0.2",
    )

    SessionService.logout_all(
        user=user,
    )

    s1.refresh_from_db()
    s2.refresh_from_db()

    assert s1.is_active is False
    assert s2.is_active is False


@pytest.mark.django_db
def test_logout_others():
    user = User.objects.create_user(
        email="user@test.com",
    )

    current = DeviceSession.objects.create(
        user=user,
        device_hash="1",
        ip_address="127.0.0.1",
    )

    other = DeviceSession.objects.create(
        user=user,
        device_hash="2",
        ip_address="127.0.0.2",
    )

    SessionService.logout_others(
        user=user,
        current_session=current,
    )

    current.refresh_from_db()
    other.refresh_from_db()

    assert current.is_active is True
    assert other.is_active is False