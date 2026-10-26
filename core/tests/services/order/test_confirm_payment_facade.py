# tests/services/order/test_confirm_payment_facade.py
from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from order.services.confirm_payment_facade import (
    confirm_order_payment_by_order_id,
)
from payment.enums import PaymentAttemptStatus, PaymentStatusType
from tests.factories.payment import PaymentAttemptFactory


pytestmark = pytest.mark.django_db


def make_success_attempt(payment, suffix: str):
    return PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        status=PaymentAttemptStatus.SUCCESS,
        authority_id=f"AUTH-{suffix}",
        gateway_reference=f"REF-{suffix}",
        gateway_transaction_id=f"TXN-{suffix}",
        response_code="100",
        gateway_message="Payment successful",
    )


class TestConfirmOrderPaymentFacade:

    def test_delegates_payment_resolution_to_canonical_service(
        self,
        order,
        mocker,
    ):
        confirm = mocker.patch(
            "order.services.confirm_payment_facade.confirm_order_payment",
            return_value=order,
        )

        result = confirm_order_payment_by_order_id(order.id)

        assert result == order
        confirm.assert_called_once_with(order_id=order.id)

    def test_does_not_select_arbitrary_payment_when_multiple_succeed(
        self,
        order,
        success_payment,
        payment_factory,
        mocker,
    ):
        another_payment = payment_factory(
            order=order,
            status=PaymentStatusType.SUCCESS,
        )
        make_success_attempt(
            another_payment,
            "ANOTHER",
        )

        confirm = mocker.patch(
            "order.services.confirm_payment_facade.confirm_order_payment",
            side_effect=ValueError(
                "Multiple successful Payments found for Order"
            ),
        )

        with pytest.raises(
            ValueError,
            match="Multiple successful Payments found",
        ):
            confirm_order_payment_by_order_id(order.id)

        confirm.assert_called_once_with(order_id=order.id)

        success_payment.refresh_from_db()
        another_payment.refresh_from_db()

        assert success_payment.is_consumed is False
        assert another_payment.is_consumed is False

    def test_translates_canonical_validation_error_to_value_error(
        self,
        order,
        mocker,
    ):
        confirm = mocker.patch(
            "order.services.confirm_payment_facade.confirm_order_payment",
            side_effect=ValidationError(
                "No successful payment found"
            ),
        )

        with pytest.raises(
            ValueError,
            match="No successful payment found",
        ):
            confirm_order_payment_by_order_id(order.id)

        confirm.assert_called_once_with(order_id=order.id)