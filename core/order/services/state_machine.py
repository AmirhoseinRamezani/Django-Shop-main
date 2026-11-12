# core/order/services/state_machine.py
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from order.events.order_event import OrderEventType
from order.models import OrderStatusType
from order.services.events import _record_order_event as record_order_event
from order.services.inventory import InventoryService
from order.services.coupon import CouponService


# Opaque application-layer capabilities for the two privileged transitions.
# They are intentionally separate and are never accepted from request data.
_PAYMENT_FINALIZATION_TOKEN = object()
_REFUND_FINALIZATION_TOKEN = object()

class OrderStateMachine:

    TRANSITIONS = {
        OrderStatusType.pending: {
            OrderStatusType.paid,
            OrderStatusType.failed,
            OrderStatusType.cancelled,
        },
        OrderStatusType.failed: {
            OrderStatusType.pending,
            OrderStatusType.cancelled,
        },
        OrderStatusType.paid: {
            OrderStatusType.processing,
            OrderStatusType.refunded,
        },
        OrderStatusType.processing: {
            OrderStatusType.shipped,
            OrderStatusType.refunded,
        },
        OrderStatusType.shipped: {
            OrderStatusType.delivered,
            OrderStatusType.return_requested,
        },
        OrderStatusType.return_requested: {
            OrderStatusType.returned,
        },
        OrderStatusType.returned: {
            OrderStatusType.refunded,
        },
        OrderStatusType.delivered: set(),
        OrderStatusType.cancelled: set(),
        OrderStatusType.refunded: set(),
    }

    @classmethod
    @transaction.atomic
    def transition(
        cls,
        *,
        order,
        to_status,
        actor=None,
        payload=None,
        _authorization=None,
        _refund_authorization=None,
    ):
        """
        Atomically transition an Order between valid states.

        The database row is re-locked here because the state machine
        is the final authority for concurrent status transitions.

        Paid-like statuses require paid_date to be populated.
        """

        order = (
            order.__class__
            .objects
            .select_for_update()
            .get(
                id=order.id,
            )
        )

        from_status = order.status

        if (
            to_status == OrderStatusType.paid
            and _authorization is not _PAYMENT_FINALIZATION_TOKEN
        ):
            raise ValidationError(
                "Orders can only be marked paid by confirm_order_payment()."
            )

        # Refund finalization has a separate, narrowly-scoped capability.
        # It cannot authorize any other transition and cannot be substituted
        # by the Payment finalization capability or a public value.
        if (
            _refund_authorization is not None
            and to_status != OrderStatusType.refunded
        ):
            raise ValidationError(
                "Refund finalization capability only authorizes Order -> REFUNDED."
            )

        if (
            to_status == OrderStatusType.refunded
            and _refund_authorization is not _REFUND_FINALIZATION_TOKEN
        ):
            raise ValidationError(
                "Orders can only be marked refunded by RefundService finalization."
            )

        if to_status not in cls.TRANSITIONS.get(
            from_status,
            set(),
        ):
            raise ValidationError(
                f"Illegal transition from "
                f"{from_status} to {to_status}"
            )

        cls._handle_side_effects(
            order,
            from_status,
            to_status,
        )

        order.status = to_status

        update_fields = [
            "status",
        ]

        # --------------------------------------------------------
        # Paid lifecycle invariant
        # --------------------------------------------------------
        #
        # Database constraint:
        #
        #     paid-like status <=> paid_date IS NOT NULL
        #
        # The state machine owns status transitions, therefore it
        # must maintain this invariant for every pending -> paid
        # transition.
        # --------------------------------------------------------

        if (
            to_status == OrderStatusType.paid
            and order.paid_date is None
        ):
            order.paid_date = timezone.now()
            update_fields.append("paid_date")

        if (
            to_status == OrderStatusType.delivered
            and order.completed_date is None
        ):
            order.completed_date = timezone.now()
            update_fields.append("completed_date")

        if (
            to_status == OrderStatusType.cancelled
            and order.cancelled_date is None
        ):
            order.cancelled_date = timezone.now()
            update_fields.append("cancelled_date")

        order.save(
            update_fields=update_fields,
        )

        record_order_event(
            order=order,
            type=cls._map_status_to_event(
                to_status,
                payload,
            ),
            actor=actor,
            payload=payload or {},
        )

        if to_status == OrderStatusType.cancelled and order.coupon_id:
            CouponService.schedule_reconciliation(order.pk)

        return order

    @staticmethod
    def _handle_side_effects(
        order,
        from_status,
        to_status,
    ):
        """
        Execute synchronous state-transition side effects.
        """

        if (
            to_status == OrderStatusType.cancelled
            and from_status in {
                OrderStatusType.pending,
                OrderStatusType.failed,
            }
        ):
            # InventoryService owns payment-evidence checks as well as the
            # reservation transition. Unknown outcomes and canonical paid
            # Payments retain consumed/reserved inventory.
            InventoryService.restore(order)

    @staticmethod
    def _map_status_to_event(
        status,
        payload=None,
    ):
        if status == OrderStatusType.cancelled:
            if (
                payload
                and payload.get("reason") == "timeout"
            ):
                return OrderEventType.EXPIRED

            return OrderEventType.CANCELLED

        event_type = {
            OrderStatusType.pending: OrderEventType.PENDING,
            OrderStatusType.failed: OrderEventType.FAILED,
            OrderStatusType.paid: OrderEventType.PAID,
            OrderStatusType.processing: OrderEventType.PROCESSING,
            OrderStatusType.shipped: OrderEventType.SHIPPED,
            OrderStatusType.delivered: OrderEventType.DELIVERED,
            OrderStatusType.return_requested: (
                OrderEventType.RETURN_REQUESTED
            ),
            OrderStatusType.returned: OrderEventType.RETURNED,
            OrderStatusType.refunded: OrderEventType.REFUNDED,
        }.get(status)

        if event_type is None:
            raise ValidationError(
                f"No OrderEventType is defined for Order status {status!r}."
            )

        return event_type