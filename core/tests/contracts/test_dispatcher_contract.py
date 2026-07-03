# tests/contracts/test_dispatcher_contract.py
import pytest

from events.dispatchers.registry import ROUTES


pytestmark = pytest.mark.django_db


def test_every_route_has_callable_handlers():

    for handlers in ROUTES.values():

        assert handlers

        for handler in handlers:

            assert callable(handler)