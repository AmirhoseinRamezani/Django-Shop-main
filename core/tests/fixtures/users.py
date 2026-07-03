import pytest

from tests.factories.accounts import (
    UserFactory,
    ProfileFactory,
)

@pytest.fixture
def user(db):
    return UserFactory()


@pytest.fixture
def profile(db, user):
    return ProfileFactory(user=user)
