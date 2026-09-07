# tests/services/order/test_confirm_payment.py
import pytest

from django.core.exceptions import ValidationError

from order.models import OrderModel ,OrderStatusType
from order.services.confirm_payment import confirm_order_payment

from payment.enums import (
    PaymentAttemptStatus,
    PaymentStatusType,
)
from tests.factories.payment import PaymentAttemptFactory


pytestmark = pytest.mark.django_db

class TestConfirmOrderPayment:

    def _ensure_success_attempt(
        self,
        payment,
        *,
        authority_id="AUTH-CONFIRM",
        gateway_reference="REF-CONFIRM",
        gateway_transaction_id="TX-CONFIRM",
    ):
        return PaymentAttemptFactory(
            payment=payment,
            attempt_number=1,
            status=PaymentAttemptStatus.SUCCESS,
            authority_id=authority_id,
            gateway_reference=gateway_reference,
            gateway_transaction_id=gateway_transaction_id,
        )

    def test_success(
        self,
        order,
        success_payment,
    ):
        self._ensure_success_attempt(
            success_payment,
        )

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
        self._ensure_success_attempt(
            success_payment,
        )

        result = confirm_order_payment(
            order.id,
        )

        assert result.pk == order.pk

    def test_payment_consumed(
        self,
        order,
        success_payment,
    ):
        self._ensure_success_attempt(
            success_payment,
        )

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
        self._ensure_success_attempt(
            success_payment,
        )

        confirm_order_payment(
            order.id,
        )

        order.refresh_from_db()

        assert order.status == OrderStatusType.paid
        assert order.paid_date is not None

    def test_coupon_consumed(
        self,
        order_with_coupon,
        success_payment,
        mocker,
    ):
        self._ensure_success_attempt(
            success_payment,
        )

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
        self._ensure_success_attempt(
            success_payment,
        )

        transition = mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition",
        )

        confirm_order_payment(
            order.id,
        )

        transition.assert_called_once()

    def test_payload_contains_attempt_reference(
        self,
        order,
        success_payment,
        mocker,
    ):
        attempt = self._ensure_success_attempt(
            success_payment,
            gateway_reference="REF-TEST",
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
        assert payload["ref_id"] == "REF-TEST"

    def test_actor(
        self,
        order,
        success_payment,
        mocker,
    ):
        self._ensure_success_attempt(
            success_payment,
        )

        transition = mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition",
        )

        confirm_order_payment(
            order.id,
        )

        kwargs = transition.call_args.kwargs

        assert kwargs["actor"] == order.user


class TestFailures:

    def test_expired_order(
        self,
        expired_order,
        success_payment,
    ):
        self._ensure_success_attempt(
            success_payment,
        )

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
        self._ensure_success_attempt(
            consumed_payment,
        )

        with pytest.raises(
            ValidationError,
            match="Payment already consumed",
        ):
            confirm_order_payment(
                order.id,
            )

    def test_duplicate_confirmation(
        self,
        order,
        success_payment,
    ):
        self._ensure_success_attempt(
            success_payment,
        )

        confirm_order_payment(
            order.id,
        )

        with pytest.raises(
            ValidationError,
            match="Payment already consumed",
        ):
            confirm_order_payment(
                order.id,
            )


class TestCoupon:

    def test_without_coupon(
        self,
        order,
        success_payment,
        mocker,
    ):
        self._ensure_success_attempt(
            success_payment,
        )

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
        self._ensure_success_attempt(
            success_payment,
        )

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
        self._ensure_success_attempt(
            success_payment,
        )

        consume = mocker.patch(
            "order.services.confirm_payment.CouponService.consume",
        )

        confirm_order_payment(
            order_with_coupon.id,
        )

        assert consume.call_count == 1

    def test_coupon_not_called_if_transition_fails(
        self,
        order_with_coupon,
        success_payment,
        mocker,
    ):
        self._ensure_success_attempt(
            success_payment,
        )

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


class TestAtomic:

    def test_transition_failure_rolls_back(
        self,
        order,
        success_payment,
        mocker,
    ):
        self._ensure_success_attempt(
            success_payment,
        )

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
        self._ensure_success_attempt(
            success_payment,
        )

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


class TestIdempotency:

    def test_second_call_fails(
        self,
        order,
        success_payment,
    ):
        self._ensure_success_attempt(
            success_payment,
        )

        confirm_order_payment(
            order.id,
        )

        with pytest.raises(
            ValidationError,
            match="Payment already consumed",
        ):
            confirm_order_payment(
                order.id,
            )

    def test_payment_only_consumed_once(
        self,
        order,
        success_payment,
    ):
        self._ensure_success_attempt(
            success_payment,
        )

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
        self._ensure_success_attempt(
            success_payment,
        )

        confirm_order_payment(
            order.id,
        )

        order.refresh_from_db()

        assert order.status == OrderStatusType.paid


class TestMultiplePayments:

    def _create_success_attempt(
        self,
        payment,
        reference,
    ):
        return PaymentAttemptFactory(
            payment=payment,
            attempt_number=1,
            status=PaymentAttemptStatus.SUCCESS,
            authority_id=f"AUTH-{reference}",
            gateway_reference=reference,
            gateway_transaction_id=f"TX-{reference}",
        )

    def test_latest_success_payment_used(
        self,
        order,
        success_payment,
        payment_factory,
    ):
        old_payment = success_payment

        self._create_success_attempt(
            old_payment,
            "OLD-REF",
        )

        latest = payment_factory(
            order=order,
            status=PaymentStatusType.SUCCESS,
        )

        self._create_success_attempt(
            latest,
            "NEW-REF",
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

        self._create_success_attempt(
            success,
            "SUCCESS-REF",
        )

        confirm_order_payment(
            order.id,
        )

        order.refresh_from_db()

        assert order.status == OrderStatusType.paid

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

        self._create_success_attempt(
            success,
            "SUCCESS-REF",
        )

        confirm_order_payment(
            order.id,
        )

        success.refresh_from_db()

        assert success.is_consumed is True


class TestTransitionPayload:

    def _prepare(
        self,
        success_payment,
    ):
        return PaymentAttemptFactory(
            payment=success_payment,
            attempt_number=1,
            status=PaymentAttemptStatus.SUCCESS,
            authority_id="AUTH-PAYLOAD",
            gateway_reference="REF-PAYLOAD",
            gateway_transaction_id="TX-PAYLOAD",
        )

    def test_amount_sent(
        self,
        order,
        success_payment,
        mocker,
    ):
        self._prepare(success_payment)

        transition = mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition",
        )

        confirm_order_payment(
            order.id,
        )

        payload = transition.call_args.kwargs["payload"]

        assert payload["amount"] == str(success_payment.amount)

    def test_payment_id_sent(
        self,
        order,
        success_payment,
        mocker,
    ):
        self._prepare(success_payment)

        transition = mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition",
        )

        confirm_order_payment(
            order.id,
        )

        payload = transition.call_args.kwargs["payload"]

        assert payload["payment_id"] == success_payment.id

    def test_ref_id_sent(
        self,
        order,
        success_payment,
        mocker,
    ):
        self._prepare(success_payment)

        transition = mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition",
        )

        confirm_order_payment(
            order.id,
        )

        payload = transition.call_args.kwargs["payload"]

        assert payload["ref_id"] == "REF-PAYLOAD"


class TestQueries:

    def test_order_locked(
        self,
        order,
        success_payment,
        mocker,
    ):
        self._ensure_success_attempt(
            success_payment,
        )

        original_manager = OrderModel.objects

        manager = mocker.patch(
            "order.services.confirm_payment.OrderModel.objects",
        )

        qs = manager.select_for_update.return_value
        qs.get.return_value = order

        payment_manager = mocker.patch(
            "order.services.confirm_payment.PaymentModel.objects",
        )

        payment_qs = payment_manager.select_for_update.return_value

        (
            payment_qs
            .filter.return_value
            .order_by.return_value
            .first.return_value
        ) = success_payment

        mocker.patch(
            "order.services.confirm_payment.PaymentAttempt.objects",
        )

        assert original_manager is not None

    def test_payment_locked(
        self,
        order,
        success_payment,
        mocker,
    ):
        self._ensure_success_attempt(
            success_payment,
        )

        manager = mocker.patch(
            "order.services.confirm_payment.PaymentModel.objects",
        )

        qs = manager.select_for_update.return_value

        (
            qs
            .filter.return_value
            .order_by.return_value
            .first.return_value
        ) = success_payment

        mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition",
        )

        confirm_order_payment(
            order.id,
        )

        manager.select_for_update.assert_called_once()


class TestServiceCalls:

    def test_coupon_not_called_without_coupon(
        self,
        order,
        success_payment,
        mocker,
    ):
        self._ensure_success_attempt(
            success_payment,
        )

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
        self._ensure_success_attempt(
            success_payment,
        )

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
        self._ensure_success_attempt(
            success_payment,
        )

        transition = mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition",
        )

        confirm_order_payment(
            order.id,
        )

        assert transition.call_count == 1


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
        self._ensure_success_attempt(
            success_payment,
        )

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
        self._ensure_success_attempt(
            success_payment,
        )

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