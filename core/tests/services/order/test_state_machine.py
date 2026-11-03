# test/services/order/test_state_machine
import pytest

from django.core.exceptions import ValidationError

from order.models import OrderStatusType
from order.services.state_machine import OrderStateMachine
from order.events.order_event import OrderEventType

pytestmark = pytest.mark.django_db


class TestOrderStateMachine:

    # ---------------------------------------------------------
    # pending -> paid
    # ---------------------------------------------------------

    def test_pending_to_paid_is_forbidden_outside_payment_finalizer(
        self,
        pending_order,
    ):
        with pytest.raises(ValidationError, match="confirm_order_payment"):
            OrderStateMachine.transition(
                order=pending_order,
                to_status=OrderStatusType.paid,
            )

        pending_order.refresh_from_db()
        assert pending_order.status == OrderStatusType.pending
        assert pending_order.paid_date is None

    # ---------------------------------------------------------
    # pending -> cancelled
    # ---------------------------------------------------------

    def test_pending_to_cancelled(
        self,
        pending_order,
        mocker,
    ):
        restore = mocker.patch(
            "order.services.state_machine.InventoryService.restore"
        )

        record = mocker.patch(
            "order.services.state_machine.record_order_event"
        )

        order = OrderStateMachine.transition(
            order=pending_order,
            to_status=OrderStatusType.cancelled,
            actor=pending_order.user,
        )

        order.refresh_from_db()

        assert order.status == OrderStatusType.cancelled

        restore.assert_called_once_with(order)

        record.assert_called_once()

    # ---------------------------------------------------------
    # pending -> expired(cancelled)
    # ---------------------------------------------------------

    def test_timeout_cancel_generates_expired_event(
        self,
        pending_order,
        mocker,
    ):
        mocker.patch(
            "order.services.state_machine.InventoryService.restore"
        )

        record = mocker.patch(
            "order.services.state_machine.record_order_event"
        )

        OrderStateMachine.transition(
            order=pending_order,
            to_status=OrderStatusType.cancelled,
            payload={
                "reason": "timeout",
            },
        )

        args = record.call_args.kwargs

        assert args["type"] == OrderEventType.EXPIRED

    # ---------------------------------------------------------
    # paid -> processing
    # ---------------------------------------------------------

    def test_paid_to_processing(
        self,
        paid_order,
        mocker,
    ):
        record = mocker.patch(
            "order.services.state_machine.record_order_event"
        )

        order = OrderStateMachine.transition(
            order=paid_order,
            to_status=OrderStatusType.processing,
        )

        order.refresh_from_db()

        assert order.status == OrderStatusType.processing

        args = record.call_args.kwargs

        assert args["type"] == OrderEventType.PROCESSING

    # ---------------------------------------------------------
    # processing -> shipped
    # ---------------------------------------------------------

    def test_processing_to_shipped(
        self,
        processing_order,
        mocker,
    ):
        mocker.patch(
            "order.services.state_machine.record_order_event"
        )

        order = OrderStateMachine.transition(
            order=processing_order,
            to_status=OrderStatusType.shipped,
        )

        order.refresh_from_db()

        assert order.status == OrderStatusType.shipped

    # ---------------------------------------------------------
    # shipped -> delivered
    # ---------------------------------------------------------

    def test_shipped_to_delivered(
        self,
        shipped_order,
        mocker,
    ):
        mocker.patch(
            "order.services.state_machine.record_order_event"
        )

        order = OrderStateMachine.transition(
            order=shipped_order,
            to_status=OrderStatusType.delivered,
        )

        order.refresh_from_db()

        assert order.status == OrderStatusType.delivered
        assert order.completed_date is not None

    def test_mark_completed_uses_canonical_delivered_transition(
        self,
        shipped_order,
        mocker,
    ):
        record = mocker.patch(
            "order.services.state_machine.record_order_event"
        )

        result = shipped_order.mark_completed()

        result.refresh_from_db()
        assert result.status == OrderStatusType.delivered
        assert result.completed_date is not None
        assert record.call_args.kwargs["type"] == OrderEventType.DELIVERED

    def test_mark_completed_rejects_non_shipped_order(
        self,
        pending_order,
    ):
        with pytest.raises(ValidationError, match="Illegal transition"):
            pending_order.mark_completed()

        pending_order.refresh_from_db()
        assert pending_order.status == OrderStatusType.pending
        assert pending_order.completed_date is None

    # ---------------------------------------------------------
    # paid -> refunded
    # ---------------------------------------------------------

    def test_paid_to_refunded(
        self,
        paid_order,
        mocker,
    ):
        record = mocker.patch(
            "order.services.state_machine.record_order_event"
        )

        order = OrderStateMachine.transition(
            order=paid_order,
            to_status=OrderStatusType.refunded,
        )

        order.refresh_from_db()

        assert order.status == OrderStatusType.refunded

        args = record.call_args.kwargs

        assert args["type"] == OrderEventType.REFUNDED

    @pytest.mark.parametrize(
        ("status", "expected_event"),
        [
            (OrderStatusType.pending, OrderEventType.PENDING),
            (OrderStatusType.failed, OrderEventType.FAILED),
            (OrderStatusType.paid, OrderEventType.PAID),
            (OrderStatusType.processing, OrderEventType.PROCESSING),
            (OrderStatusType.shipped, OrderEventType.SHIPPED),
            (OrderStatusType.delivered, OrderEventType.DELIVERED),
            (
                OrderStatusType.return_requested,
                OrderEventType.RETURN_REQUESTED,
            ),
            (OrderStatusType.returned, OrderEventType.RETURNED),
            (OrderStatusType.refunded, OrderEventType.REFUNDED),
        ],
    )
    def test_status_event_mapping_is_explicit(
        self,
        status,
        expected_event,
    ):
        assert (
            OrderStateMachine._map_status_to_event(status)
            == expected_event
        )

    def test_unmapped_status_does_not_fall_back_to_admin_note(self):
        with pytest.raises(ValidationError, match="No OrderEventType"):
            OrderStateMachine._map_status_to_event(999)

    # ---------------------------------------------------------
    # illegal transition
    # ---------------------------------------------------------

    def test_illegal_transition(
        self,
        paid_order,
    ):
        with pytest.raises(ValidationError):

            OrderStateMachine.transition(
                order=paid_order,
                to_status=OrderStatusType.pending,
            )

    # ---------------------------------------------------------
    # delivered is terminal
    # ---------------------------------------------------------

    def test_terminal_state(
        self,
        delivered_order,
    ):
        with pytest.raises(ValidationError):

            OrderStateMachine.transition(
                order=delivered_order,
                to_status=OrderStatusType.processing,
            )

    # ---------------------------------------------------------
    # lock row
    # ---------------------------------------------------------

    def test_select_for_update_called(
        self,
        pending_order,
        mocker,
    ):
        manager = mocker.patch.object(
            pending_order.__class__,
            "objects",
        )

        qs = manager.select_for_update.return_value

        qs.get.return_value = pending_order

        mocker.patch(
            "order.services.state_machine.record_order_event"
        )

        mocker.patch(
            "order.services.state_machine.OrderStateMachine._handle_side_effects"
        )

        OrderStateMachine.transition(
            order=pending_order,
            to_status=OrderStatusType.cancelled,
        )

        manager.select_for_update.assert_called_once()

    # ---------------------------------------------------------
    # side effects always executed before save
    # ---------------------------------------------------------

    def test_side_effect_called(
        self,
        pending_order,
        mocker,
    ):
        side = mocker.patch(
            "order.services.state_machine.OrderStateMachine._handle_side_effects"
        )

        mocker.patch(
            "order.services.state_machine.record_order_event"
        )

        OrderStateMachine.transition(
            order=pending_order,
            to_status=OrderStatusType.cancelled,
        )

        side.assert_called_once()

    # ---------------------------------------------------------
    # payload forwarded
    # ---------------------------------------------------------

    def test_payload_forwarded(
        self,
        paid_order,
        mocker,
    ):
        record = mocker.patch(
            "order.services.state_machine.record_order_event"
        )

        payload = {
            "payment_id": 12,
            "gateway": "zarinpal",
        }

        OrderStateMachine.transition(
            order=paid_order,
            to_status=OrderStatusType.refunded,
            payload=payload,
        )

        kwargs = record.call_args.kwargs

        assert kwargs["payload"] == payload

    # ---------------------------------------------------------
    # actor forwarded
    # ---------------------------------------------------------

    def test_actor_forwarded(
        self,
        paid_order,
        admin_user,
        mocker,
    ):
        record = mocker.patch(
            "order.services.state_machine.record_order_event"
        )

        OrderStateMachine.transition(
            order=paid_order,
            to_status=OrderStatusType.processing,
            actor=admin_user,
        )

        kwargs = record.call_args.kwargs

        assert kwargs["actor"] == admin_user