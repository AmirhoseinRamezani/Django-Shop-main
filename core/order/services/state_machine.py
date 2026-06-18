# order/services/state_machine.py
from django.db import transaction
from django.core.exceptions import ValidationError
from django.db.models import F

from order.models import OrderStatusType
from order.events.order_event import OrderEventType
from order.services.events import record_order_event
from shop.models import ProductModel
from django.utils.translation import gettext as _


class OrderStateMachine:

    TRANSITIONS = {

        # Payment phase
        OrderStatusType.pending: {
            OrderStatusType.paid,
            OrderStatusType.failed,
            OrderStatusType.cancelled,
        },

        OrderStatusType.failed: {
            OrderStatusType.pending,
            OrderStatusType.cancelled,
        },

        # Paid flow
        OrderStatusType.paid: {
            OrderStatusType.processing,
            OrderStatusType.refunded,
        },

        OrderStatusType.processing: {
            OrderStatusType.shipped,
            OrderStatusType.cancelled,
        },

        # Shipping
        OrderStatusType.shipped: {
            OrderStatusType.delivered,
            OrderStatusType.return_requested,
        },

        OrderStatusType.delivered: {
            OrderStatusType.return_requested,
        },

        # Return
        OrderStatusType.return_requested: {
            OrderStatusType.returned,
        },

        OrderStatusType.returned: {
            OrderStatusType.refunded,
        },

        # Terminal
        OrderStatusType.refunded: set(),
        OrderStatusType.cancelled: set(),
    }

    @classmethod
    @transaction.atomic
    def transition(cls, *, order, to_status, actor=None, payload=None):

        order = (
            order.__class__.objects
            .select_for_update()
            .get(id=order.id)
        )

        from_status = order.status

        allowed = cls.TRANSITIONS.get(from_status, set())
        if to_status not in allowed:
            raise ValidationError(_(
                f"Illegal transition from {from_status} to {to_status}"
            ))

        cls._handle_side_effects(order, from_status, to_status)

        order.status = to_status
        order.save(update_fields=["status"])

        record_order_event(
            order=order,
            type=cls._map_status_to_event(to_status, payload),
            actor=actor,
            payload=payload or {},
        )

        return order

    @staticmethod
    def _handle_side_effects(order, from_status, to_status):

        # restore stock if cancel before shipping
        if (
            to_status == OrderStatusType.cancelled
            and from_status in {
                OrderStatusType.pending,
                OrderStatusType.processing,
            }
        ):
            for item in order.order_items.all():
                ProductModel.objects.filter(
                    id=item.product_id
                ).update(
                    stock=F("stock") + item.quantity
                )

    @staticmethod
    def _map_status_to_event(status, payload=None):

        mapping = {
            OrderStatusType.paid: OrderEventType.PAID,
            OrderStatusType.shipped: OrderEventType.SHIPPED,
            OrderStatusType.delivered: OrderEventType.DELIVERED,
            OrderStatusType.return_requested: OrderEventType.RETURN_REQUESTED,
            OrderStatusType.returned: OrderEventType.RETURNED,
            OrderStatusType.refunded: OrderEventType.REFUNDED,
        }

        if status == OrderStatusType.cancelled:
            if payload and payload.get("reason") == "timeout":
                return OrderEventType.EXPIRED
            return OrderEventType.CANCELLED

        return mapping.get(status, OrderEventType.ADMIN_NOTE)