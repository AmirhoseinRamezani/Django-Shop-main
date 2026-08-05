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
