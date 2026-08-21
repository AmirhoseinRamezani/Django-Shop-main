# tests/services/order/test_confirm_payment.py
import pytest

from django.core.exceptions import ValidationError

from order.models import (
    OrderStatusType,
)

from payment.enums import PaymentStatusType
from order.services.confirm_payment import (
    confirm_order_payment,
)

pytestmark = pytest.mark.django_db


class TestConfirmOrderPayment:

    def test_success(
        self,
        order,
        success_payment,
    ):

        result = confirm_order_payment(order.id)

        order.refresh_from_db()
        success_payment.refresh_from_db()

        assert result == order
        assert order.status == OrderStatusType.paid
        assert success_payment.is_consumed is True

    def test_return_order(
        self,
        order,
        success_payment,
    ):

        result = confirm_order_payment(order.id)

        assert result.pk == order.pk

    def test_payment_consumed(
        self,
        order,
        success_payment,
    ):

        confirm_order_payment(order.id)

        success_payment.refresh_from_db()

        assert success_payment.is_consumed

    def test_order_paid(
        self,
        order,
        success_payment,
    ):

        confirm_order_payment(order.id)

        order.refresh_from_db()

        assert order.status == OrderStatusType.paid

    def test_coupon_consumed(
        self,
        order_with_coupon,
        success_payment,
        coupon,
        mocker,
    ):

        consume = mocker.patch(
            "order.services.confirm_payment.CouponService.consume"
        )

        confirm_order_payment(order_with_coupon.id)

        consume.assert_called_once()

    def test_transition_called(
        self,
        order,
        success_payment,
        mocker,
    ):

        transition = mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition"
        )

        confirm_order_payment(order.id)

        transition.assert_called_once()

    def test_payload_contains_ref(
        self,
        order,
        success_payment,
        mocker,
    ):

        transition = mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition"
        )

        confirm_order_payment(order.id)

        kwargs = transition.call_args.kwargs

        payload = kwargs["payload"]

        assert payload["payment_id"] == success_payment.id
        assert payload["ref_id"] == success_payment.ref_id

    def test_actor(
        self,
        order,
        success_payment,
        mocker,
    ):

        transition = mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition"
        )

        confirm_order_payment(order.id)

        kwargs = transition.call_args.kwargs

        assert kwargs["actor"] == order.user
        
# Failure Scenarios        
class TestFailures:

    def test_expired_order(
        self,
        expired_order,
        success_payment,
    ):

        with pytest.raises(ValueError):

            confirm_order_payment(
                expired_order.id,
            )

    def test_no_success_payment(
        self,
        order,
    ):

        with pytest.raises(ValidationError):

            confirm_order_payment(order.id)

    def test_failed_payment(
        self,
        order,
        failed_payment,
    ):

        with pytest.raises(ValidationError):

            confirm_order_payment(order.id)

    def test_pending_payment(
        self,
        order,
        pending_payment,
    ):

        with pytest.raises(ValidationError):

            confirm_order_payment(order.id)

    def test_already_consumed(
        self,
        order,
        consumed_payment,
    ):

        with pytest.raises(ValidationError):

            confirm_order_payment(order.id)

    def test_duplicate_confirmation(
        self,
        order,
        success_payment,
    ):

        confirm_order_payment(order.id)

        with pytest.raises(ValidationError):

            confirm_order_payment(order.id)
            
# Coupon
class TestCoupon:

    def test_without_coupon(
        self,
        order,
        success_payment,
        mocker,
    ):

        consume = mocker.patch(
            "order.services.confirm_payment.CouponService.consume"
        )

        confirm_order_payment(order.id)

        consume.assert_not_called()

    def test_with_coupon(
        self,
        order_with_coupon,
        success_payment,
        mocker,
    ):

        consume = mocker.patch(
            "order.services.confirm_payment.CouponService.consume"
        )

        confirm_order_payment(order_with_coupon.id)

        consume.assert_called_once()

    def test_coupon_called_once(
        self,
        order_with_coupon,
        success_payment,
        mocker,
    ):

        consume = mocker.patch(
            "order.services.confirm_payment.CouponService.consume"
        )

        confirm_order_payment(order_with_coupon.id)

        assert consume.call_count == 1
        
# Atomicity
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

            confirm_order_payment(order.id)

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
        
# Idempotency
class TestIdempotency:

    def test_second_call_fails(
        self,
        order,
        success_payment,
    ):

        confirm_order_payment(order.id)

        with pytest.raises(ValidationError):

            confirm_order_payment(order.id)

    def test_payment_only_consumed_once(
        self,
        order,
        success_payment,
    ):

        confirm_order_payment(order.id)

        success_payment.refresh_from_db()

        assert success_payment.is_consumed

    def test_order_not_paid_twice(
        self,
        order,
        success_payment,
    ):

        confirm_order_payment(order.id)

        order.refresh_from_db()

        assert order.status == OrderStatusType.paid
        
# ------------------------------------------------------------------
# Multiple Payments
# ------------------------------------------------------------------


class TestMultiplePayments:

    def test_latest_success_payment_used(
        self,
        order,
        success_payment,
        payment_factory,
    ):
        """
        Newest successful payment must be consumed.
        Older success payments remain untouched.
        """

        old_payment = success_payment

        latest = payment_factory(
            order=order,
            status=PaymentStatusType.SUCCESS,
            ref_id="NEW-REF",
        )

        confirm_order_payment(order.id)

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

        payment_factory(
            order=order,
            status=PaymentStatusType.SUCCESS,
        )

        confirm_order_payment(order.id)

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

        confirm_order_payment(order.id)

        success.refresh_from_db()

        assert success.is_consumed
        
# ------------------------------------------------------------------
# Transition Payload
# ------------------------------------------------------------------


class TestTransitionPayload:

    def test_amount_sent(
        self,
        order,
        success_payment,
        mocker,
    ):
        transition = mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition"
        )

        confirm_order_payment(order.id)

        payload = transition.call_args.kwargs["payload"]

        assert payload["amount"] == str(order.final_price)

    def test_payment_id_sent(
        self,
        order,
        success_payment,
        mocker,
    ):
        transition = mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition"
        )

        confirm_order_payment(order.id)

        payload = transition.call_args.kwargs["payload"]

        assert payload["payment_id"] == success_payment.id

    def test_ref_id_sent(
        self,
        order,
        success_payment,
        mocker,
    ):
        transition = mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition"
        )

        confirm_order_payment(order.id)

        payload = transition.call_args.kwargs["payload"]

        assert payload["ref_id"] == success_payment.ref_id
        
# ------------------------------------------------------------------
# Query Behaviour
# ------------------------------------------------------------------


class TestQueries:

    def test_order_locked(
        self,
        mocker,
        order,
    ):
        manager = mocker.patch(
            "order.services.confirm_payment.OrderModel.objects"
        )

        qs = manager.select_for_update.return_value

        qs.get.return_value = order

        payment_qs = mocker.Mock()

        payment = mocker.Mock()

        payment.status = PaymentStatusType.SUCCESS
        payment.is_consumed = False

        payment_qs.filter.return_value.order_by.return_value.first.return_value = payment

        mocker.patch(
            "order.services.confirm_payment.PaymentModel.objects",
            payment_qs,
        )

        mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition"
        )

        confirm_order_payment(order.id)

        manager.select_for_update.assert_called_once()

    def test_payment_locked(
        self,
        order,
        success_payment,
        mocker,
    ):
        manager = mocker.patch(
            "order.services.confirm_payment.PaymentModel.objects"
        )

        qs = manager.select_for_update.return_value

        qs.filter.return_value.order_by.return_value.first.return_value = success_payment

        mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition"
        )

        confirm_order_payment(order.id)

        manager.select_for_update.assert_called_once()
        
# ------------------------------------------------------------------
# Service Calls
# ------------------------------------------------------------------


class TestServiceCalls:

    def test_coupon_not_called_without_coupon(
        self,
        order,
        success_payment,
        mocker,
    ):
        consume = mocker.patch(
            "order.services.confirm_payment.CouponService.consume"
        )

        confirm_order_payment(order.id)

        consume.assert_not_called()

    def test_coupon_called_once(
        self,
        order_with_coupon,
        success_payment,
        mocker,
    ):
        consume = mocker.patch(
            "order.services.confirm_payment.CouponService.consume"
        )

        confirm_order_payment(order_with_coupon.id)

        assert consume.call_count == 1

    def test_transition_called_once(
        self,
        order,
        success_payment,
        mocker,
    ):
        transition = mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition"
        )

        confirm_order_payment(order.id)

        assert transition.call_count == 1
        
# ------------------------------------------------------------------
# Failure Ordering
# ------------------------------------------------------------------


class TestFailureOrdering:

    def test_transition_not_called_without_payment(
        self,
        order,
        mocker,
    ):
        transition = mocker.patch(
            "order.services.confirm_payment.OrderStateMachine.transition"
        )

        with pytest.raises(ValidationError):
            confirm_order_payment(order.id)

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
            "order.services.confirm_payment.CouponService.consume"
        )

        with pytest.raises(RuntimeError):
            confirm_order_payment(order_with_coupon.id)

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
            confirm_order_payment(order.id)

        success_payment.refresh_from_db()

        assert success_payment.is_consumed is False