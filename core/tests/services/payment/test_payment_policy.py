# tests/services/payment/test_payment_policy.py
import pytest

from payment.policies import PaymentPolicy
from payment.exceptions import PaymentCreationForbiddenError

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.service,
]

class TestPaymentPolicy:

    def test_can_pay(
        self,
        order_builder,
    ):
    
        scenario = order_builder.build() if hasattr(order_builder, 'build') else order_builder()
        order = scenario.order if hasattr(scenario, 'order') else scenario
    
        assert PaymentPolicy.can_create_payment(order) is True

    def test_expired(
        self,
        order_builder,
    ):
        scenario = order_builder.expired().build()
        order = scenario.order if hasattr(scenario, 'order') else scenario

        with pytest.raises(PaymentCreationForbiddenError):
            PaymentPolicy.can_create_payment(order)

    def test_pending_exists(
        self,
        order_builder,
        payment_factory,
    ):
        scenario = order_builder.build() if hasattr(order_builder, 'build') else order_builder()
        order = scenario.order if hasattr(scenario, 'order') else scenario

        payment_factory(order=order)

        # The Order row is still payable, so the pure policy remains true.
        assert PaymentPolicy.can_create_payment(order) is True
