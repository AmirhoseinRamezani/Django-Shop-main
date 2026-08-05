# tests/services/payment/test_payment_policy.py
import pytest

from django.core.exceptions import ValidationError

from payment.policies import PaymentPolicy


pytestmark = [
    pytest.mark.django_db,
    pytest.mark.service,
]


class TestPaymentPolicy:

    def test_can_pay(
        self,
        order_factory,
    ):
        order = order_factory()

        assert (
            PaymentPolicy.can_start_payment(order)
            is True
        )

    def test_expired(
        self,
        order_factory,
    ):
        order = order_factory(
            expired=True,
        )

        with pytest.raises(
            ValidationError
        ):
            PaymentPolicy.can_start_payment(
                order
            )

    def test_pending_exists(
        self,
        order_factory,
        payment_factory,
    ):
        order = order_factory()

        payment_factory(
            order=order,
            pending=True,
        )

        with pytest.raises(
            ValidationError
        ):
            PaymentPolicy.can_start_payment(
                order
            )