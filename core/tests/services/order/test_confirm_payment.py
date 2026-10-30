# tests/services/order/test_confirm_payment.py
from __future__ import annotations

import pytest

from django.core.exceptions import ValidationError

from order.events.order_event import OrderEvent, OrderEventType
from order.models import OrderStatusType
from order.services.confirm_payment import confirm_order_payment

from payment.enums import (
    PaymentAttemptStatus,
    PaymentStatusType,
)
from payment.models import PaymentAttempt
from payment.repositories.payment_attempt_repository import (
    PaymentAttemptRepository,
)
from tests.factories.payment import PaymentAttemptFactory


pytestmark = pytest.mark.django_db


# ==========================================================
# HELPERS
# ==========================================================


def _make_success_attempt(
    payment,
    *,
    authority_id: str = "AUTH-TEST",
    gateway_reference: str = "REF-TEST",
    gateway_transaction_id: str = "TXN-TEST",
    clear_existing: bool = True,
):
    """
    Create a successful PaymentAttempt for a Payment.

    By default, the Payment is normalized to exactly one successful
    attempt. Tests that explicitly exercise multiple successful
    attempts can disable cleanup.
    """

    if clear_existing:
        payment.attempts.all().delete()

    attempt_number = PaymentAttemptRepository.next_attempt_number(
        payment,
    )

    return PaymentAttemptFactory(
        payment=payment,
        attempt_number=attempt_number,
        status=PaymentAttemptStatus.SUCCESS,
        authority_id=authority_id,
        gateway_reference=gateway_reference,
        gateway_transaction_id=gateway_transaction_id,
        response_code="100",
        gateway_message="Payment successful",
    )


def _patch_transition(mocker, order):
    """
    Mock OrderStateMachine.transition while preserving its production
    return contract: it returns an OrderModel.
    """

    return mocker.patch(
        "order.services.confirm_payment.OrderStateMachine.transition",
        return_value=order,
    )


# ==========================================================
# SUCCESS
# ==========================================================


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

    def test_coupon_reconciliation_scheduled(
        self,
        order_with_coupon,
        success_payment,
        mocker,
    ):
        schedule = mocker.patch(
            "order.services.confirm_payment.CouponService.schedule_reconciliation",
        )

        confirm_order_payment(
            order_with_coupon.id,
        )

        schedule.assert_called_once_with(
            order_with_coupon.pk,
        )

    def test_transition_called(
        self,
        order,
        success_payment,
        mocker,
    ):
        transition = _patch_transition(
            mocker,
            order,
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

        transition = _patch_transition(
            mocker,
            order,
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
        transition = _patch_transition(
            mocker,
            order,
        )

        confirm_order_payment(
            order.id,
        )

        kwargs = transition.call_args.kwargs

        assert kwargs["actor"] == order.user


# ==========================================================
# FAILURE SCENARIOS
# ==========================================================


class TestFailures:

    def test_expired_order_is_rejected_before_payment_lookup(
        self,
        expired_order,
        mocker,
    ):
        expired_order.refresh_from_db()

        assert expired_order.is_expired() is True

        payment_lookup = mocker.patch(
            "order.services.confirm_payment.PaymentRepository.successful_for_order",
        )

        with pytest.raises(
            ValidationError,
            match="Order expired",
        ):
            confirm_order_payment(
                expired_order.id,
            )

        payment_lookup.assert_not_called()

    def test_expired_order_does_not_consume_successful_payment(
        self,
        expired_order,
        success_payment,
    ):
        assert success_payment.order_id == expired_order.id

        with pytest.raises(
            ValidationError,
            match="Order expired",
        ):
            confirm_order_payment(
                expired_order.id,
                payment_id=success_payment.id,
            )

        success_payment.refresh_from_db()
        expired_order.refresh_from_db()

        assert success_payment.is_consumed is False
        assert expired_order.status == OrderStatusType.pending

    def test_expired_order(
        self,
        expired_order,
        success_payment,
    ):
        from django.utils import timezone

        expired_order.refresh_from_db()
        success_payment.refresh_from_db()

        assert expired_order.expire_at <= timezone.now(), (
            "Fixture did not expire the order: "
            f"expire_at={expired_order.expire_at!r}"
        )
        assert expired_order.is_expired() is True
        assert expired_order.status == OrderStatusType.pending
        assert success_payment.order_id == expired_order.id
        assert success_payment.is_consumed is False

        with pytest.raises(
            ValidationError,
            match="Order expired",
        ):
            confirm_order_payment(
                expired_order.id,
                payment_id=success_payment.id,
            )

        success_payment.refresh_from_db()

        assert success_payment.is_consumed is False

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
            match="Consumed Payment is inconsistent with Order state or PAID event",
        ):
            confirm_order_payment(
                order.id,
                payment_id=consumed_payment.id,
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


# ==========================================================
# COUPON
# ==========================================================


class TestCoupon:

    def test_without_coupon(
        self,
        order,
        success_payment,
        mocker,
    ):
        schedule = mocker.patch(
            "order.services.confirm_payment.CouponService.schedule_reconciliation",
        )

        confirm_order_payment(
            order.id,
        )

        schedule.assert_not_called()

    def test_with_coupon(
        self,
        order_with_coupon,
        success_payment,
        mocker,
    ):
        schedule = mocker.patch(
            "order.services.confirm_payment.CouponService.schedule_reconciliation",
         )

        confirm_order_payment(
            order_with_coupon.id,
        )

        schedule.assert_called_once()

    def test_coupon_reconciliation_scheduled_once(
        self,
        order_with_coupon,
        success_payment,
        mocker,
    ):
        schedule = mocker.patch(
            "order.services.confirm_payment.CouponService.schedule_reconciliation",
        )

        confirm_order_payment(
            order_with_coupon.id,
        )

        assert schedule.call_count == 1


# ==========================================================
# ATOMICITY
# ==========================================================


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

    def test_coupon_reconciliation_is_scheduled_after_financial_finalization(
        self,
        order_with_coupon,
        success_payment,
        mocker,
    ):
        schedule = mocker.patch(
            "order.services.confirm_payment.CouponService.schedule_reconciliation",
        )

        result = confirm_order_payment(order_with_coupon.id)

        success_payment.refresh_from_db()

        order_with_coupon.refresh_from_db()

        assert result.status == OrderStatusType.paid
        assert success_payment.is_consumed is True
        assert order_with_coupon.status == OrderStatusType.paid
        schedule.assert_called_once_with(order_with_coupon.id)


# ==========================================================
# IDEMPOTENCY
# ==========================================================


class TestIdempotency:

    def test_second_call_is_idempotent(
        self,
        order,
        success_payment,
    ):
        first = confirm_order_payment(
            order.id,
        )

        second = confirm_order_payment(
            order.id,
        )

        assert first.pk == second.pk
        assert second.status == OrderStatusType.paid

    def test_consumed_payment_requires_matching_paid_event_attempt(
        self,
        order,
        success_payment,
        mocker,
    ):
        attempt = PaymentAttemptRepository.latest_for_payment(
            success_payment.pk,
        )

        OrderEvent.objects.create(
            order=order,
            type=OrderEventType.PAID,
            payload={
                "payment_id": success_payment.pk,
                "attempt_id": attempt.pk + 1,
            },
        )

        success_payment.is_consumed = True
        success_payment.save(update_fields=("is_consumed",))

        transition = mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition",
        )

        with pytest.raises(
            ValidationError,
            match="Consumed Payment is inconsistent with Order state or PAID event",
        ):
            confirm_order_payment(
                order.id,
                payment_id=success_payment.id,
            )

        transition.assert_not_called()

    def test_consumed_payment_requires_successful_attempt(
        self,
        order,
        success_payment,
    ):
        success_payment.attempts.all().delete()
        success_payment.is_consumed = True
        success_payment.save(update_fields=("is_consumed",))

        with pytest.raises(
            ValidationError,
            match="No successful payment attempt found",
        ):
            confirm_order_payment(
                order.id,
                payment_id=success_payment.id,
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


# ==========================================================
# MULTIPLE PAYMENTS
# ==========================================================


class TestMultiplePayments:

    def test_ambiguous_success_payments_are_rejected(
        self,
        order,
        success_payment,
        payment_factory,
    ):
        another = payment_factory(
            order=order,
            status=PaymentStatusType.SUCCESS,
        )

        _make_success_attempt(
            another,
            authority_id="AUTH-ANOTHER",
            gateway_reference="REF-ANOTHER",
            gateway_transaction_id="TXN-ANOTHER",
        )

        with pytest.raises(
            ValidationError,
            match="Multiple successful Payments found for Order",
        ):
            confirm_order_payment(
                order.id,
            )

        success_payment.refresh_from_db()
        another.refresh_from_db()

        assert success_payment.is_consumed is False
        assert another.is_consumed is False

    def test_explicit_payment_id_uses_exact_payment_lock(
        self,
        order,
        success_payment,
        mocker,
    ):
        successful_for_order = mocker.patch(
            "order.services.confirm_payment.PaymentRepository.successful_for_order",
            side_effect=AssertionError(
                "explicit payment confirmation must not discover a payment by order"
            ),
        )

        confirm_order_payment(
            order.id,
            payment_id=success_payment.id,
        )

        successful_for_order.assert_not_called()
        success_payment.refresh_from_db()

        assert success_payment.is_consumed is True

    def test_explicit_payment_id_selects_exact_successful_payment(
        self,
        order,
        success_payment,
        payment_factory,
    ):
        another = payment_factory(
            order=order,
            status=PaymentStatusType.SUCCESS,
        )

        _make_success_attempt(
            another,
            authority_id="AUTH-ANOTHER",
            gateway_reference="REF-ANOTHER",
            gateway_transaction_id="TXN-ANOTHER",
        )

        confirm_order_payment(
            order.id,
            payment_id=success_payment.id,
        )

        success_payment.refresh_from_db()
        another.refresh_from_db()

        assert success_payment.is_consumed is True
        assert another.is_consumed is False

    def test_payment_id_from_another_order_is_rejected(
        self,
        order,
        order_factory,
        payment_factory,
    ):
        other_order = order_factory()

        other_payment = payment_factory(
            order=other_order,
            status=PaymentStatusType.SUCCESS,
        )

        _make_success_attempt(
            other_payment,
            authority_id="AUTH-OTHER-ORDER",
            gateway_reference="REF-OTHER-ORDER",
            gateway_transaction_id="TXN-OTHER-ORDER",
        )

        with pytest.raises(
            ValidationError,
            match="No successful payment found",
        ):
            confirm_order_payment(
                order.id,
                payment_id=other_payment.id,
            )

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
        success.refresh_from_db()

        assert order.status == OrderStatusType.paid
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

    def test_confirmation_requires_exactly_one_successful_attempt_for_payment(
        self,
        order,
        payment_factory,
    ):
        payment = payment_factory(
            order=order,
            status=PaymentStatusType.SUCCESS,
        )

        _make_success_attempt(
            payment,
            authority_id="AUTH-FIRST",
            gateway_reference="REF-FIRST",
            gateway_transaction_id="TXN-FIRST",
        )

        _make_success_attempt(
            payment,
            authority_id="AUTH-SECOND",
            gateway_reference="REF-SECOND",
            gateway_transaction_id="TXN-SECOND",
            clear_existing=False,
        )

        with pytest.raises(
            ValidationError,
            match="Multiple successful payment attempts",
        ):
            confirm_order_payment(
                order.id,
                payment_id=payment.id,
            )

        payment.refresh_from_db()

        attempts = list(
            PaymentAttemptRepository.successful_for_payment(
                payment.pk,
            ).order_by(
                "attempt_number",
                "id",
            )
        )

        assert payment.is_consumed is False
        assert len(attempts) == 2
        assert {
            attempt.gateway_reference
            for attempt in attempts
        } == {
            "REF-FIRST",
            "REF-SECOND",
        }

    def test_confirmation_does_not_use_attempt_from_another_payment(
        self,
        order,
        payment_factory,
    ):
        payment = payment_factory(
            order=order,
            status=PaymentStatusType.SUCCESS,
        )

        unrelated_payment = payment_factory(
            order=order,
            status=PaymentStatusType.SUCCESS,
        )

        _make_success_attempt(
            unrelated_payment,
            authority_id="AUTH-UNRELATED",
            gateway_reference="REF-UNRELATED",
            gateway_transaction_id="TXN-UNRELATED",
        )

        with pytest.raises(
            ValidationError,
        ):
            confirm_order_payment(
                order.id,
                payment_id=payment.id,
            )

        payment.refresh_from_db()
        unrelated_payment.refresh_from_db()

        assert payment.is_consumed is False
        assert unrelated_payment.is_consumed is False

    def test_failed_attempt_does_not_authorize_successful_payment(
        self,
        order,
        payment_factory,
    ):
        payment = payment_factory(
            order=order,
            status=PaymentStatusType.SUCCESS,
        )

        payment.attempts.all().delete()

        failed_attempt = PaymentAttemptFactory(
            payment=payment,
            attempt_number=1,
            status=PaymentAttemptStatus.FAILED,
            authority_id="AUTH-FAILED",
            gateway_reference="REF-FAILED",
            gateway_transaction_id="TXN-FAILED",
        )

        with pytest.raises(
            ValidationError,
            match="No successful payment attempt found",
        ):
            confirm_order_payment(
                order.id,
                payment_id=payment.id,
            )

        payment.refresh_from_db()
        failed_attempt.refresh_from_db()

        assert payment.is_consumed is False
        assert failed_attempt.status == PaymentAttemptStatus.FAILED

    def test_successful_attempt_for_other_payment_cannot_authorize_target(
        self,
        order,
        payment_factory,
    ):
        target = payment_factory(
            order=order,
            status=PaymentStatusType.SUCCESS,
        )

        other = payment_factory(
            order=order,
            status=PaymentStatusType.SUCCESS,
        )

        _make_success_attempt(
            other,
            authority_id="AUTH-OTHER",
            gateway_reference="REF-OTHER",
            gateway_transaction_id="TXN-OTHER",
        )

        with pytest.raises(
            ValidationError,
        ):
            confirm_order_payment(
                order.id,
                payment_id=target.id,
            )

        target.refresh_from_db()
        other.refresh_from_db()

        assert target.is_consumed is False
        assert other.is_consumed is False


# ==========================================================
# TRANSITION PAYLOAD
# ==========================================================


class TestTransitionPayload:

    def test_amount_sent(
        self,
        order,
        success_payment,
        mocker,
    ):
        transition = _patch_transition(
            mocker,
            order,
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
        transition = _patch_transition(
            mocker,
            order,
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

        transition = _patch_transition(
            mocker,
            order,
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

        transition = _patch_transition(
            mocker,
            order,
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
        transition = _patch_transition(
            mocker,
            order,
        )

        confirm_order_payment(
            order.id,
        )

        payload = transition.call_args.kwargs["payload"]

        assert payload["currency"] == str(
            success_payment.currency,
        )


# ==========================================================
# SERVICE CALLS
# ==========================================================


class TestServiceCalls:

    def test_coupon_reconciliation_not_scheduled_without_coupon(
        self,
        order,
        success_payment,
        mocker,
    ):
        schedule = mocker.patch(
            "order.services.confirm_payment.CouponService.schedule_reconciliation",
        )

        confirm_order_payment(
            order.id,
        )

        schedule.assert_not_called()

    def test_coupon_reconciliation_scheduled_once(
        self,
        order_with_coupon,
        success_payment,
        mocker,
    ):
        schedule = mocker.patch(
            "order.services.confirm_payment.CouponService.schedule_reconciliation",
        )

        confirm_order_payment(
            order_with_coupon.id,
        )

        assert schedule.call_count == 1

    def test_transition_called_once(
        self,
        order,
        success_payment,
        mocker,
    ):
        transition = _patch_transition(
            mocker,
            order,
        )

        confirm_order_payment(
            order.id,
        )

        assert transition.call_count == 1


# ==========================================================
# FAILURE ORDERING
# ==========================================================


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

    def test_coupon_reconciliation_not_scheduled_if_transition_fails(
        self,
        order_with_coupon,
        success_payment,
        mocker,
    ):
        mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition",
            side_effect=RuntimeError(),
        )

        schedule = mocker.patch(
            "order.services.confirm_payment.CouponService.schedule_reconciliation",
        )

        with pytest.raises(RuntimeError):
            confirm_order_payment(
                order_with_coupon.id,
            )

        schedule.assert_not_called()

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


# ==========================================================
# PAYMENT / PAYMENT ATTEMPT BOUNDARIES
# ==========================================================


class TestPaymentAttemptIntegrity:

    def test_payment_without_successful_attempt_is_not_consumed(
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
                payment_id=payment.id,
            )

        payment.refresh_from_db()

        assert payment.is_consumed is False

    def test_failed_attempt_does_not_authorize_payment_consumption(
        self,
        order,
        payment_factory,
    ):
        payment = payment_factory(
            order=order,
            status=PaymentStatusType.SUCCESS,
        )

        payment.attempts.all().delete()

        PaymentAttemptFactory(
            payment=payment,
            attempt_number=1,
            status=PaymentAttemptStatus.FAILED,
            authority_id="AUTH-FAILED",
            gateway_reference="REF-FAILED",
            gateway_transaction_id="TXN-FAILED",
        )

        with pytest.raises(
            ValidationError,
            match="No successful payment attempt found",
        ):
            confirm_order_payment(
                order.id,
                payment_id=payment.id,
            )

        payment.refresh_from_db()

        assert payment.is_consumed is False

    def test_payment_from_another_order_cannot_be_consumed(
        self,
        order,
        order_factory,
        payment_factory,
    ):
        foreign_order = order_factory()

        foreign_payment = payment_factory(
            order=foreign_order,
            status=PaymentStatusType.SUCCESS,
        )

        _make_success_attempt(
            foreign_payment,
            authority_id="AUTH-FOREIGN",
            gateway_reference="REF-FOREIGN",
            gateway_transaction_id="TXN-FOREIGN",
        )

        with pytest.raises(
            ValidationError,
            match="No successful payment found",
        ):
            confirm_order_payment(
                order.id,
                payment_id=foreign_payment.id,
            )

        foreign_payment.refresh_from_db()

        assert foreign_payment.is_consumed is False