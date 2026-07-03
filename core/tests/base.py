# tests/base.py

import pytest

from factory.django import DjangoModelFactory

from tests.assertions import (
    refresh,
    assert_order_created,
    assert_order_paid,
    assert_payment_success,
    assert_payment_pending,
    assert_processed,
)

from tests.helpers import (
    fake_gateway,
    freeze_time,
)


pytestmark = pytest.mark.django_db


class BaseTestCase:
    """
    Base class for all service/integration/e2e tests.

    Every helper should be stateless.
    """

    refresh = staticmethod(refresh)

    freeze_time = staticmethod(freeze_time)

    fake_gateway = staticmethod(fake_gateway)

    assert_order_created = staticmethod(
        assert_order_created
    )

    assert_order_paid = staticmethod(
        assert_order_paid
    )

    assert_payment_success = staticmethod(
        assert_payment_success
    )

    assert_payment_pending = staticmethod(
        assert_payment_pending
    )

    assert_processed = staticmethod(
        assert_processed
    )

    def gateway(self, mocker):

        gateway = self.fake_gateway()

        mocker.patch(
            "payment.services.services.ZarinPalSandbox",
            return_value=gateway,
        )

        return gateway

    def dispatch(self, mocker):

        return mocker.patch(
            "events.services.processor.dispatch"
        )

    def publish(self, mocker):

        return mocker.patch(
            "events.bus.publish_event"
        )
        
class BaseFactory(DjangoModelFactory):
    class Meta:
        abstract = True


class BaseBuilder:
    """
    Parent class for builders.
    """
    pass


class BaseTest:
    """
    Parent class for test classes.
    """
    pass

# from tests.assertions import (
#     refresh,
#     assert_order_created,
#     assert_order_paid,
#     assert_payment_success,
#     assert_payment_pending,
#     assert_processed,
# )


# class BaseTestCase:

#     refresh = staticmethod(refresh)

#     assert_order_created = staticmethod(assert_order_created)

#     assert_order_paid = staticmethod(assert_order_paid)

#     assert_payment_success = staticmethod(assert_payment_success)

#     assert_payment_pending = staticmethod(assert_payment_pending)

#     assert_processed = staticmethod(assert_processed)


# class BaseFactory:
#     """
#     Parent class for all Builders/Factories.
#     """
#     pass