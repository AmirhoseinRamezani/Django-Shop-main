# tests/contracts/test_factory_contract.py
import pytest


pytestmark = pytest.mark.django_db


def test_factories_can_be_imported():

    from tests.factories.accounts import UserFactory
    from tests.factories.shop import ProductFactory
    from tests.factories.cart import CartFactory
    from tests.factories.order import OrderFactory
    from tests.factories.payment import PaymentFactory
    from tests.factories.events import OutboxEventFactory

    assert UserFactory
    assert ProductFactory
    assert CartFactory
    assert OrderFactory
    assert PaymentFactory
    assert OutboxEventFactory