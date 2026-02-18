# accounts/tests/conftest.py
import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()


@pytest.fixture
def email():
    return "user@example.com"

