# tests/fixtures/addresses.py

import pytest

from tests.factories.shop import AddressFactory


@pytest.fixture
def address_factory():
    return AddressFactory
