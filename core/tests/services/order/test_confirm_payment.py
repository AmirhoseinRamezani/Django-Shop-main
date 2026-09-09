# tests/services/order/test_confirm_payment.py
from __future__ import annotations

import pytest

from django.core.exceptions import ValidationError

from order.models import OrderStatusType
from order.services.confirm_payment import confirm_order_payment

from payment.enums import (
    PaymentAttemptStatus,
    PaymentStatusType,
)
from payment.repositories.payment_attempt_repository import (
    PaymentAttemptRepository,
)
from tests.factories.payment import PaymentAttemptFactory


pytestmark = pytest.mark.django_db


# ==================================================================
# HELPERS
# ==================================================================

def _make_success_attempt(
    payment,
    *,
    authority_id: str = "AUTH-TEST",
    gateway_reference: str = "REF-TEST",
    gateway_transaction_id: str = "TXN-TEST",
):
    """
    Create exactly one successful attempt for a Payment.

    This helper deliberately owns gateway identity through
    PaymentAttempt rather than Payment.
    """

    payment.attempts.all().delete()

    return PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        status=PaymentAttemptStatus.SUCCESS,
        authority_id=authority_id,
        gateway_reference=gateway_reference,
        gateway_transaction_id=gateway_transaction_id,
        response_code="100",
        gateway_message="Payment successful",
    )


# ==================================================================
# SUCCESS
# ==================================================================

class TestConfirmOrderPayment:

    def test_success(
        self,
        order,
        success_payment,
    ):
        result = confirm_order_payment(
            order.id,
        )

        order.refresh_from_db()
        success_payment.refresh_from_db()

        assert result.pk == order.pk
        assert order.status == OrderStatusType.paid
        assert order.paid_date is not None
        assert success_payment.is_consumed is True

    def test_return_order(
        self,
        order,
        success_payment,
    ):
        result = confirm_order_payment(
            order.id,
        )

        assert result.pk == order.pk

    def test_payment_consumed(
        self,
        order,
        success_payment,
    ):
        confirm_order_payment(
            order.id,
        )

        success_payment.refresh_from_db()

        assert success_payment.is_consumed is True

    def test_order_paid(
        self,
        order,
        success_payment,
    ):
        confirm_order_payment(
            order.id,
        )

        order.refresh_from_db()

        assert order.status == OrderStatusType.paid
        assert order.is_paid
        assert order.paid_date is not None

    def test_coupon_consumed(
        self,
        order_with_coupon,
        success_payment,
        mocker,
    ):
        consume = mocker.patch(
            "order.services.confirm_payment.CouponService.consume",
        )

        confirm_order_payment(
            order_with_coupon.id,
        )

        consume.assert_called_once_with(
            order_with_coupon.coupon,
        )

    def test_transition_called(
        self,
        order,
        success_payment,
        mocker,
    ):
        transition = mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition",
        )

        confirm_order_payment(
            order.id,
        )

        transition.assert_called_once()

    def test_payload_contains_attempt_gateway_reference(
        self,
        order,
        success_payment,
        mocker,
    ):
        attempt = PaymentAttemptRepository.latest_for_payment(
            success_payment.pk,
        )

        transition = mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition",
        )

        confirm_order_payment(
            order.id,
        )

        kwargs = transition.call_args.kwargs
        payload = kwargs["payload"]

        assert payload["payment_id"] == success_payment.id
        assert payload["attempt_id"] == attempt.id
        assert payload["ref_id"] == attempt.gateway_reference

    def test_actor(
        self,
        order,
        success_payment,
        mocker,
    ):
        transition = mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition",
        )

        confirm_order_payment(
            order.id,
        )

        kwargs = transition.call_args.kwargs

        assert kwargs["actor"] == order.user


# ==================================================================
# FAILURE SCENARIOS
# ==================================================================

class TestFailures:

    def test_expired_order(
        self,
        expired_order,
        success_payment,
    ):
        with pytest.raises(ValidationError, match="Order expired"):
            confirm_order_payment(
                expired_order.id,
            )

    def test_no_success_payment(
        self,
        order,
    ):
        with pytest.raises(
            ValidationError,
            match="No successful payment found",
        ):
            confirm_order_payment(
                order.id,
            )

    def test_failed_payment(
        self,
        order,
        failed_payment,
    ):
        with pytest.raises(
            ValidationError,
            match="No successful payment found",
        ):
            confirm_order_payment(
                order.id,
            )

    def test_pending_payment(
        self,
        order,
        pending_payment,
    ):
        with pytest.raises(
            ValidationError,
            match="No successful payment found",
        ):
            confirm_order_payment(
                order.id,
            )

    def test_already_consumed(
        self,
        order,
        consumed_payment,
    ):
        with pytest.raises(
            ValidationError,
            match="Payment has already been consumed",
        ):
            confirm_order_payment(
                order.id,
            )

    def test_successful_payment_without_successful_attempt(
        self,
        order,
        payment_factory,
    ):
        payment = payment_factory(
            order=order,
            status=PaymentStatusType.SUCCESS,
        )

        payment.attempts.all().delete()

        with pytest.raises(
            ValidationError,
            match="No successful payment attempt found",
        ):
            confirm_order_payment(
                order.id,
            )

        payment.refresh_from_db()

        assert payment.is_consumed is False


# ==================================================================
# COUPON
# ==================================================================

class TestCoupon:

    def test_without_coupon(
        self,
        order,
        success_payment,
        mocker,
    ):
        consume = mocker.patch(
            "order.services.confirm_payment.CouponService.consume",
        )

        confirm_order_payment(
            order.id,
        )

        consume.assert_not_called()

    def test_with_coupon(
        self,
        order_with_coupon,
        success_payment,
        mocker,
    ):
        consume = mocker.patch(
            "order.services.confirm_payment.CouponService.consume",
        )

        confirm_order_payment(
            order_with_coupon.id,
        )

        consume.assert_called_once()

    def test_coupon_called_once(
        self,
        order_with_coupon,
        success_payment,
        mocker,
    ):
        consume = mocker.patch(
            "order.services.confirm_payment.CouponService.consume",
        )

        confirm_order_payment(
            order_with_coupon.id,
        )

        assert consume.call_count == 1


# ==================================================================
# ATOMICITY
# ==================================================================

class TestAtomic:

    def test_transition_failure_rolls_back(
        self,
        order,
        success_payment,
        mocker,
    ):
        mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition",
            side_effect=RuntimeError(),
        )

        with pytest.raises(RuntimeError):
            confirm_order_payment(
                order.id,
            )

        success_payment.refresh_from_db()

        assert success_payment.is_consumed is False

    def test_coupon_failure_rolls_back(
        self,
        order_with_coupon,
        success_payment,
        mocker,
    ):
        mocker.patch(
            "order.services.confirm_payment.CouponService.consume",
            side_effect=RuntimeError(),
        )

        with pytest.raises(RuntimeError):
            confirm_order_payment(
                order_with_coupon.id,
            )

        success_payment.refresh_from_db()

        assert success_payment.is_consumed is False

        order_with_coupon.refresh_from_db()

        assert order_with_coupon.status == OrderStatusType.pending


# ==================================================================
# IDEMPOTENCY
# ==================================================================

class TestIdempotency:

    def test_second_call_fails(
        self,
        order,
        success_payment,
    ):
        confirm_order_payment(
            order.id,
        )

        with pytest.raises(
            ValidationError,
            match="Payment has already been consumed",
        ):
            confirm_order_payment(
                order.id,
            )

    def test_payment_only_consumed_once(
        self,
        order,
        success_payment,
    ):
        confirm_order_payment(
            order.id,
        )

        success_payment.refresh_from_db()

        assert success_payment.is_consumed is True

    def test_order_not_paid_twice(
        self,
        order,
        success_payment,
    ):
        confirm_order_payment(
            order.id,
        )

        order.refresh_from_db()

        assert order.status == OrderStatusType.paid


# ==================================================================
# MULTIPLE PAYMENTS
# ==================================================================

class TestMultiplePayments:

    def test_latest_success_payment_used(
        self,
        order,
        success_payment,
        payment_factory,
    ):
        old_payment = success_payment

        latest = payment_factory(
            order=order,
            status=PaymentStatusType.SUCCESS,
        )

        _make_success_attempt(
            latest,
            authority_id="AUTH-LATEST",
            gateway_reference="REF-LATEST",
            gateway_transaction_id="TXN-LATEST",
        )

        confirm_order_payment(
            order.id,
        )

        old_payment.refresh_from_db()
        latest.refresh_from_db()

        assert latest.is_consumed is True
        assert old_payment.is_consumed is False

    def test_ignore_failed_payments(
        self,
        order,
        payment_factory,
    ):
        payment_factory(
            order=order,
            status=PaymentStatusType.FAILED,
        )

        success = payment_factory(
            order=order,
            status=PaymentStatusType.SUCCESS,
        )

        _make_success_attempt(
            success,
            authority_id="AUTH-SUCCESS",
            gateway_reference="REF-SUCCESS",
            gateway_transaction_id="TXN-SUCCESS",
        )

        confirm_order_payment(
            order.id,
        )

        order.refresh_from_db()

        assert order.status == OrderStatusType.paid

        success.refresh_from_db()

        assert success.is_consumed is True

    def test_ignore_pending_payments(
        self,
        order,
        payment_factory,
    ):
        payment_factory(
            order=order,
            status=PaymentStatusType.PENDING,
        )

        success = payment_factory(
            order=order,
            status=PaymentStatusType.SUCCESS,
        )

        _make_success_attempt(
            success,
            authority_id="AUTH-SUCCESS",
            gateway_reference="REF-SUCCESS",
            gateway_transaction_id="TXN-SUCCESS",
        )

        confirm_order_payment(
            order.id,
        )

        success.refresh_from_db()

        assert success.is_consumed is True


# ==================================================================
# TRANSITION PAYLOAD
# ==================================================================

class TestTransitionPayload:

    def test_amount_sent(
        self,
        order,
        success_payment,
        mocker,
    ):
        transition = mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition",
        )

        confirm_order_payment(
            order.id,
        )

        payload = transition.call_args.kwargs["payload"]

        assert payload["amount"] == str(
            success_payment.amount,
        )

    def test_payment_id_sent(
        self,
        order,
        success_payment,
        mocker,
    ):
        transition = mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition",
        )

        confirm_order_payment(
            order.id,
        )

        payload = transition.call_args.kwargs["payload"]

        assert payload["payment_id"] == success_payment.id

    def test_attempt_id_sent(
        self,
        order,
        success_payment,
        mocker,
    ):
        attempt = PaymentAttemptRepository.latest_for_payment(
            success_payment.pk,
        )

        transition = mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition",
        )

        confirm_order_payment(
            order.id,
        )

        payload = transition.call_args.kwargs["payload"]

        assert payload["attempt_id"] == attempt.id

    def test_ref_id_sent(
        self,
        order,
        success_payment,
        mocker,
    ):
        attempt = PaymentAttemptRepository.latest_for_payment(
            success_payment.pk,
        )

        transition = mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition",
        )

        confirm_order_payment(
            order.id,
        )

        payload = transition.call_args.kwargs["payload"]

        assert payload["ref_id"] == attempt.gateway_reference

    def test_currency_sent(
        self,
        order,
        success_payment,
        mocker,
    ):
        transition = mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition",
        )

        confirm_order_payment(
            order.id,
        )

        payload = transition.call_args.kwargs["payload"]

        assert payload["currency"] == str(
            success_payment.currency,
        )


# ==================================================================
# SERVICE CALLS
# ==================================================================

class TestServiceCalls:

    def test_coupon_not_called_without_coupon(
        self,
        order,
        success_payment,
        mocker,
    ):
        consume = mocker.patch(
            "order.services.confirm_payment.CouponService.consume",
        )

        confirm_order_payment(
            order.id,
        )

        consume.assert_not_called()

    def test_coupon_called_once(
        self,
        order_with_coupon,
        success_payment,
        mocker,
    ):
        consume = mocker.patch(
            "order.services.confirm_payment.CouponService.consume",
        )

        confirm_order_payment(
            order_with_coupon.id,
        )

        assert consume.call_count == 1

    def test_transition_called_once(
        self,
        order,
        success_payment,
        mocker,
    ):
        transition = mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition",
        )

        confirm_order_payment(
            order.id,
        )

        assert transition.call_count == 1


# ==================================================================
# FAILURE ORDERING
# ==================================================================

class TestFailureOrdering:

    def test_transition_not_called_without_payment(
        self,
        order,
        mocker,
    ):
        transition = mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition",
        )

        with pytest.raises(ValidationError):
            confirm_order_payment(
                order.id,
            )

        transition.assert_not_called()

    def test_coupon_not_called_if_transition_fails(
        self,
        order_with_coupon,
        success_payment,
        mocker,
    ):
        mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition",
            side_effect=RuntimeError(),
        )

        consume = mocker.patch(
            "order.services.confirm_payment.CouponService.consume",
        )

        with pytest.raises(RuntimeError):
            confirm_order_payment(
                order_with_coupon.id,
            )

        consume.assert_not_called()

    def test_payment_not_consumed_after_transition_failure(
        self,
        order,
        success_payment,
        mocker,
    ):
        mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition",
            side_effect=RuntimeError(),
        )

        with pytest.raises(RuntimeError):
            confirm_order_payment(
                order.id,
            )

        success_payment.refresh_from_db()

        assert success_payment.is_consumed is False