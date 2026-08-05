# # test/services/order/test_state_machine
# import pytest

# from django.core.exceptions import ValidationError

# from tests.base import BaseTestCase

# from order.services.state_machine import OrderStateMachine
# from order.models import OrderStatusType


# pytestmark = [
#     pytest.mark.django_db,
#     pytest.mark.service,
# ]


# class TestOrderStateMachine(BaseTestCase):

#     def test_pending_to_paid(
#         self,
#         order_factory,
#     ):
#         order = order_factory()

#         OrderStateMachine.transition(
#             order=order,
#             to_status=OrderStatusType.paid,
#         )

#         self.assert_order_paid(order)

#     def test_paid_to_processing(
#         self,
#         order_factory,
#     ):
#         order = order_factory(
#             paid=True,
#         )

#         OrderStateMachine.transition(
#             order=order,
#             to_status=OrderStatusType.processing,
#         )

#         order.refresh_from_db()

#         assert (
#             order.status
#             == OrderStatusType.processing
#         )

#     def test_processing_to_shipped(
#         self,
#         order_factory,
#     ):
#         order = order_factory(
#             processing=True,
#         )

#         OrderStateMachine.transition(
#             order=order,
#             to_status=OrderStatusType.shipped,
#         )

#         order.refresh_from_db()

#         assert (
#             order.status
#             == OrderStatusType.shipped
#         )

#     def test_shipped_to_delivered(
#         self,
#         order_factory,
#     ):
#         order = order_factory(
#             shipped=True,
#         )

#         OrderStateMachine.transition(
#             order=order,
#             to_status=OrderStatusType.delivered,
#         )

#         order.refresh_from_db()

#         assert (
#             order.status
#             == OrderStatusType.delivered
#         )

#     def test_return_request(
#         self,
#         order_factory,
#     ):
#         order = order_factory(
#             shipped=True,
#         )

#         OrderStateMachine.transition(
#             order=order,
#             to_status=OrderStatusType.return_requested,
#         )

#         order.refresh_from_db()

#         assert (
#             order.status
#             == OrderStatusType.return_requested
#         )

#     def test_returned(
#         self,
#         order_factory,
#     ):
#         order = order_factory(
#             return_requested=True,
#         )

#         OrderStateMachine.transition(
#             order=order,
#             to_status=OrderStatusType.returned,
#         )

#         order.refresh_from_db()

#         assert (
#             order.status
#             == OrderStatusType.returned
#         )

#     def test_refunded(
#         self,
#         order_factory,
#     ):
#         order = order_factory(
#             returned=True,
#         )

#         OrderStateMachine.transition(
#             order=order,
#             to_status=OrderStatusType.refunded,
#         )

#         order.refresh_from_db()

#         assert (
#             order.status
#             == OrderStatusType.refunded
#         )

#     @pytest.mark.parametrize(
#         "from_status,to_status",
#         [
#             (
#                 OrderStatusType.pending,
#                 OrderStatusType.processing,
#             ),
#             (
#                 OrderStatusType.pending,
#                 OrderStatusType.shipped,
#             ),
#             (
#                 OrderStatusType.processing,
#                 OrderStatusType.paid,
#             ),
#             (
#                 OrderStatusType.delivered,
#                 OrderStatusType.processing,
#             ),
#             (
#                 OrderStatusType.cancelled,
#                 OrderStatusType.pending,
#             ),
#             (
#                 OrderStatusType.refunded,
#                 OrderStatusType.processing,
#             ),
#         ]
#     )
#     def test_invalid_transition(
#         self,
#         order_factory,
#         from_status,
#         to_status,
#     ):
#         order = order_factory(
#             status=from_status,
#         )

#         with pytest.raises(
#             ValidationError
#         ):
#             OrderStateMachine.transition(
#                 order=order,
#                 to_status=to_status,
#             )

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

    def test_pending_to_paid(
        self,
        paid_order,
        mocker,
    ):
        paid_order.status = OrderStatusType.pending
        paid_order.save(update_fields=["status"])

        record = mocker.patch(
            "order.services.state_machine.record_order_event"
        )

        handle = mocker.patch(
            "order.services.state_machine.OrderStateMachine._handle_side_effects"
        )

        order = OrderStateMachine.transition(
            order=paid_order,
            to_status=OrderStatusType.paid,
            actor=paid_order.user,
            payload={"ref": "123"},
        )

        order.refresh_from_db()

        assert order.status == OrderStatusType.paid

        handle.assert_called_once_with(
            order,
            OrderStatusType.pending,
            OrderStatusType.paid,
        )

        record.assert_called_once_with(
            order=order,
            type=OrderEventType.PAID,
            actor=paid_order.user,
            payload={"ref": "123"},
        )

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

        assert args["type"] == OrderEventType.ADMIN_NOTE

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