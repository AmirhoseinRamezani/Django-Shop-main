# tests/flows/test_refund_flow.py
import pytest

from django.core.exceptions import ValidationError

from order.models import OrderStatusType
from payment.enums import (
    PaymentStatusType,
)

from order.services.state_machine import OrderStateMachine
from payment.services.refund import RefundService

pytestmark = pytest.mark.django_db


class TestRefundFlow:

    def test_refund_success(
        self,
        paid_order,
        success_payment,
        admin_user,
    ):

        service = RefundService()
        result = service.execute_refund(payment_id=payment.id, reason="Customer request")

        success_payment.refresh_from_db()
        paid_order.refresh_from_db()

        assert success_payment.is_refunded is True
        assert paid_order.status == OrderStatusType.refunded

    def test_payment_status_unchanged(
        self,
        paid_order,
        success_payment,
        admin_user,
    ):

        refund_payment(
            payment=success_payment,
            actor=admin_user,
        )

        success_payment.refresh_from_db()

        assert success_payment.status == PaymentStatusType.SUCCESS

    def test_order_state_changed(
        self,
        paid_order,
        success_payment,
        admin_user,
    ):

        refund_payment(
            payment=success_payment,
            actor=admin_user,
        )

        paid_order.refresh_from_db()

        assert paid_order.status == OrderStatusType.refunded

    def test_transition_called(
        self,
        paid_order,
        success_payment,
        admin_user,
        mocker,
    ):

        transition = mocker.patch(
            "payment.services.refund.OrderStateMachine.transition"
        )

        refund_payment(
            payment=success_payment,
            actor=admin_user,
        )

        transition.assert_called_once()

    def test_event_contains_payment(
        self,
        paid_order,
        success_payment,
        admin_user,
        mocker,
    ):

        transition = mocker.patch(
            "payment.services.refund.OrderStateMachine.transition"
        )

        refund_payment(
            payment=success_payment,
            actor=admin_user,
        )

        payload = transition.call_args.kwargs["payload"]

        assert payload["payment_id"] == success_payment.id

    def test_event_actor(
        self,
        paid_order,
        success_payment,
        admin_user,
        mocker,
    ):

        transition = mocker.patch(
            "payment.services.refund.OrderStateMachine.transition"
        )

        refund_payment(
            payment=success_payment,
            actor=admin_user,
        )

        assert transition.call_args.kwargs["actor"] == admin_user

    def test_coupon_rollback_called(
        self,
        paid_order_with_coupon,
        success_payment,
        admin_user,
        mocker,
    ):

        rollback = mocker.patch(
            "payment.services.refund.CouponService.rollback"
        )

        refund_payment(
            payment=success_payment,
            actor=admin_user,
        )

        rollback.assert_called_once()

    def test_coupon_not_called_without_coupon(
        self,
        paid_order,
        success_payment,
        admin_user,
        mocker,
    ):

        rollback = mocker.patch(
            "payment.services.refund.CouponService.rollback"
        )

        refund_payment(
            payment=success_payment,
            actor=admin_user,
        )

        rollback.assert_not_called()

    def test_payment_marked_refunded(
        self,
        paid_order,
        success_payment,
        admin_user,
    ):

        refund_payment(
            payment=success_payment,
            actor=admin_user,
        )

        success_payment.refresh_from_db()

        assert success_payment.is_refunded

    def test_return_payment(
        self,
        paid_order,
        success_payment,
        admin_user,
    ):

        payment = refund_payment(
            payment=success_payment,
            actor=admin_user,
        )

        assert payment.pk == success_payment.pk
        
# Failure Scenarios
class TestFailures:

    def test_pending_payment(
        self,
        pending_payment,
        admin_user,
    ):

        with pytest.raises(ValidationError):

            refund_payment(
                payment=pending_payment,
                actor=admin_user,
            )

    def test_failed_payment(
        self,
        failed_payment,
        admin_user,
    ):

        with pytest.raises(ValidationError):

            refund_payment(
                payment=failed_payment,
                actor=admin_user,
            )

    def test_already_refunded(
        self,
        refunded_payment,
        admin_user,
    ):

        with pytest.raises(ValidationError):

            refund_payment(
                payment=refunded_payment,
                actor=admin_user,
            )

    def test_double_refund(
        self,
        success_payment,
        admin_user,
    ):

        refund_payment(
            payment=success_payment,
            actor=admin_user,
        )

        with pytest.raises(ValidationError):

            refund_payment(
                payment=success_payment,
                actor=admin_user,
            )

    def test_transition_failure(
        self,
        success_payment,
        admin_user,
        mocker,
    ):

        mocker.patch(
            "payment.services.refund.OrderStateMachine.transition",
            side_effect=RuntimeError(),
        )

        with pytest.raises(RuntimeError):

            refund_payment(
                payment=success_payment,
                actor=admin_user,
            )

        success_payment.refresh_from_db()

        assert success_payment.is_refunded is False

    def test_coupon_failure(
        self,
        paid_order_with_coupon,
        success_payment,
        admin_user,
        mocker,
    ):

        mocker.patch(
            "payment.services.refund.CouponService.rollback",
            side_effect=RuntimeError(),
        )

        with pytest.raises(RuntimeError):

            refund_payment(
                payment=success_payment,
                actor=admin_user,
            )

        success_payment.refresh_from_db()

        assert success_payment.is_refunded is False
        
# Atomicity
class TestAtomicity:

    def test_database_rollback(
        self,
        success_payment,
        admin_user,
        mocker,
    ):

        mocker.patch(
            "payment.services.refund.OrderStateMachine.transition",
            side_effect=RuntimeError(),
        )

        with pytest.raises(RuntimeError):

            refund_payment(
                payment=success_payment,
                actor=admin_user,
            )

        success_payment.refresh_from_db()

        assert success_payment.is_refunded is False

    def test_coupon_rollback_transaction(
        self,
        paid_order_with_coupon,
        success_payment,
        admin_user,
        mocker,
    ):

        mocker.patch(
            "payment.services.refund.CouponService.rollback",
            side_effect=Exception(),
        )

        with pytest.raises(Exception):

            refund_payment(
                payment=success_payment,
                actor=admin_user,
            )

        success_payment.refresh_from_db()

        assert success_payment.is_refunded is False
        
        
# Idempotency
class TestIdempotency:

    def test_only_once(
        self,
        success_payment,
        admin_user,
    ):

        refund_payment(
            payment=success_payment,
            actor=admin_user,
        )

        with pytest.raises(ValidationError):

            refund_payment(
                payment=success_payment,
                actor=admin_user,
            )

    def test_order_not_changed_twice(
        self,
        paid_order,
        success_payment,
        admin_user,
    ):

        refund_payment(
            payment=success_payment,
            actor=admin_user,
        )

        paid_order.refresh_from_db()

        assert paid_order.status == OrderStatusType.refunded

    def test_payment_not_refunded_twice(
        self,
        success_payment,
        admin_user,
    ):

        refund_payment(
            payment=success_payment,
            actor=admin_user,
        )

        success_payment.refresh_from_db()

        assert success_payment.is_refunded