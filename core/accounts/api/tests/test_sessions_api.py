# accounts/api/tests/test_sessions_api.py
import uuid
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models.device_session import DeviceSession
from accounts.models.refresh_token import RefreshToken
from accounts.models.user import User
from accounts.services.jwt import JWTService


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        email="test@example.com",
        password="pass1234"
    )


@pytest.fixture
def another_user(db):
    return User.objects.create_user(
        email="other@example.com",
        password="pass1234"
    )


def create_session_for_user(user):
    session = DeviceSession.objects.create(
        user=user,
        ip_address="127.0.0.1",
        user_agent="pytest",
        is_active=True,
    )

    RefreshToken.objects.create(
        user=user,
        session=session,
        token=str(uuid.uuid4()),
        is_revoked=False,
    )

    access = JWTService.create_access_token(
        user_id=str(user.id),
        session_id=str(session.id),
    )

    return session, access


@pytest.mark.django_db
def test_list_only_user_sessions(api_client, user, another_user):
    session, access = create_session_for_user(user)
    create_session_for_user(another_user)

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    url = reverse("accounts-api:session-list")
    response = api_client.get(url)

    assert response.status_code == 200
    assert len(response.data) == 1
    assert response.data[0]["id"] == str(session.id)


@pytest.mark.django_db
def test_revoke_session(api_client, user):
    session, access = create_session_for_user(user)

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    url = reverse(
        "accounts-api:session-revoke",
        kwargs={"session_id": session.id},
    )

    response = api_client.delete(url)

    assert response.status_code == 204

    session.refresh_from_db()
    assert session.is_active is False

    assert RefreshToken.objects.filter(
        session=session,
        is_revoked=False
    ).count() == 0


@pytest.mark.django_db
def test_cannot_revoke_other_user_session(api_client, user, another_user):
    session, _ = create_session_for_user(another_user)
    _, access = create_session_for_user(user)

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    url = reverse(
        "accounts-api:session-revoke",
        kwargs={"session_id": session.id},
    )

    response = api_client.delete(url)
    assert response.status_code == 404


@pytest.mark.django_db
def test_logout_all(api_client, user):
    create_session_for_user(user)
    session2, access = create_session_for_user(user)

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    url = reverse("accounts-api:logout")
    response = api_client.post(url)

    assert response.status_code == 200

    assert DeviceSession.objects.filter(
        user=user,
        is_active=True
    ).count() == 1  # current one still active

    logout_all_url = reverse("accounts-api:logout")

@pytest.mark.django_db
def test_logout_all_devices(api_client, user):
    create_session_for_user(user)
    _, access = create_session_for_user(user)

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    url = reverse("accounts-api:logout-all")
    response = api_client.post(url)

    assert response.status_code == 200

    assert DeviceSession.objects.filter(
        user=user,
        is_active=True
    ).count() == 0

    assert RefreshToken.objects.filter(
        user=user,
        is_revoked=False
    ).count() == 0

@pytest.mark.django_db
def test_logout_other_sessions(api_client, user):
    # session 1
    create_session_for_user(user)

    # current session
    current_session, access = create_session_for_user(user)

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    url = reverse("accounts-api:logout-others")
    response = api_client.post(url)

    assert response.status_code == 200

    # only current must remain active
    active_sessions = DeviceSession.objects.filter(
        user=user,
        is_active=True,
    )

    assert active_sessions.count() == 1
    assert active_sessions.first().id == current_session.id

    # all other refresh tokens revoked
    assert RefreshToken.objects.filter(
        user=user,
        session__id=current_session.id,
        is_revoked=False,
    ).count() == 1
