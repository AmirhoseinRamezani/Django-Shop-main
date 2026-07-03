# tests/services/order/test_confirm_payment.py
import pytest

from django.core.exceptions import ValidationError

from order.models import OrderStatusType
from order.services.confirm_payment import confirm_order_payment

from payment.models import PaymentStatusType

from tests.assertions import (
    refresh,
    assert_order_paid,
    assert_payment_consumed,
)

pytestmark = pytest.mark.django_db


class TestConfirmOrderPayment:

    def test_confirm_success(
        self,
        order,
        successful_payment,
    ):
        confirm_order_payment(order.id)

        refresh(
            order,
            successful_payment,
        )

        assert_order_paid(order)
        assert_payment_consumed(successful_payment)

    def test_transition_called(
        self,
        order,
        successful_payment,
        mocker,
    ):
        transition = mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition"
        )

        confirm_order_payment(order.id)

        transition.assert_called_once()

    def test_latest_success_payment_consumed(
        self,
        order,
        payment_factory,
    ):
        payment_factory(
            order=order,
            success=True,
        )

        latest = payment_factory(
            order=order,
            success=True,
        )

        confirm_order_payment(order.id)

        refresh(latest)

        assert latest.is_consumed

    def test_failed_payment_rejected(
        self,
        order,
        payment_factory,
    ):
        payment_factory(
            order=order,
            status=PaymentStatusType.failed,
        )

        with pytest.raises(ValidationError):
            confirm_order_payment(order.id)

    def test_without_success_payment(
        self,
        order,
    ):
        with pytest.raises(ValidationError):
            confirm_order_payment(order.id)

    def test_consumed_payment_rejected(
        self,
        consumed_payment,
    ):
        with pytest.raises(ValidationError):
            confirm_order_payment(
                consumed_payment.order_id,
            )

    def test_expired_order_rejected(
        self,
        expired_order,
        successful_payment_for_expired_order,
    ):
        with pytest.raises(ValueError):
            confirm_order_payment(
                expired_order.id,
            )

    def test_idempotent(
        self,
        order,
        successful_payment,
    ):
        confirm_order_payment(order.id)

        with pytest.raises(ValidationError):
            confirm_order_payment(order.id)