# core/order/services/state_machine.py
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from order.events.order_event import OrderEventType
from order.models import OrderStatusType
from order.services.events import record_order_event
from order.services.inventory import InventoryService


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
            OrderStatusType.cancelled,
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
    ):
        order = (
            order.__class__
            .objects
            .select_for_update()
            .get(pk=order.pk)
        )

        from_status = order.status

        if to_status not in cls.TRANSITIONS.get(from_status, set()):
            raise ValidationError(
                f"Illegal transition from {from_status} to {to_status}"
            )

        cls._handle_side_effects(
            order,
            from_status,
            to_status,
        )

        order.status = to_status

        update_fields = ["status"]

        # DB invariant:
        # paid-like orders must always have paid_date.
        if (
            to_status == OrderStatusType.paid
            and order.paid_date is None
        ):
            order.paid_date = timezone.now()
            update_fields.append("paid_date")

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

        return order

    @staticmethod
    def _handle_side_effects(
        order,
        from_status,
        to_status,
    ):
        if (
            from_status == OrderStatusType.pending
            and to_status == OrderStatusType.cancelled
        ):
            InventoryService.restore(order)

    @staticmethod
    def _map_status_to_event(
        status,
        payload=None,
    ):
        if status == OrderStatusType.cancelled:
            if payload and payload.get("reason") == "timeout":
                return OrderEventType.EXPIRED

            return OrderEventType.CANCELLED

        return {
            OrderStatusType.paid: OrderEventType.PAID,
            OrderStatusType.refunded: OrderEventType.REFUNDED,
        }.get(
            status,
            OrderEventType.ADMIN_NOTE,
        )