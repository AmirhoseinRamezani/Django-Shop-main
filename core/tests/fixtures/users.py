# tests/fixtures/users.py
import pytest


from tests.factories.accounts import (
    UserFactory,
    ProfileFactory,
    DeviceSessionFactory,
    RefreshTokenFactory,
)

@pytest.fixture
def user_factory():
    return UserFactory

@pytest.fixture
def user(db):
    return UserFactory()


@pytest.fixture
def profile(db, **kwargs):
    return ProfileFactory()
    # return UserFactory()


@pytest.fixture
def admin_user(db):
    return UserFactory(admin=True)


@pytest.fixture
def device_session(db, user):
    return DeviceSessionFactory(user=user)


@pytest.fixture
def email(user):
    return user.email
