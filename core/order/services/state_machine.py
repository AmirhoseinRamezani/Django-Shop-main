# order/services/state_machine.py
from PIL.Image import ImagePointTransform
from django.db import transaction
from django.core.exceptions import ValidationError
from django.db.models import F
from django.utils import timezone

from order.models import OrderStatusType
from order.events.order_event import OrderEventType
from order.services.events import record_order_event
from shop.models import ProductModel
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
    def transition(cls, *, order, to_status, actor=None, payload=None):

        # 🔒 lock row
        order = (
            order.__class__
            .objects
            .select_for_update()
            .get(id=order.id)
        )

        from_status = order.status

        if to_status not in cls.TRANSITIONS.get(from_status, set()):
            raise ValidationError(
                f"Illegal transition from {from_status} to {to_status}"
            )

        # 🔥 Domain-specific side effects
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

        # restore stock when cancelling unpaid order
        if (
            from_status == OrderStatusType.pending
            and to_status == OrderStatusType.cancelled
        ):
            InventoryService.restore(order)
            # for item in order.order_items.select_related("product"):
            #     ProductModel.objects.filter(
            #         id=item.product_id
            #     ).update(
            #         stock=F("stock") + item.quantity
            #     )

    @staticmethod
    def _map_status_to_event(status, payload=None):

        if status == OrderStatusType.cancelled:
            if payload and payload.get("reason") == "timeout":
                return OrderEventType.EXPIRED
            return OrderEventType.CANCELLED

        return {
            OrderStatusType.paid: OrderEventType.PAID,
            OrderStatusType.refunded: OrderEventType.REFUNDED,
        }.get(status, OrderEventType.ADMIN_NOTE)
        
    
    
    # if (
    #     from_status == OrderStatusType.paid
    #     and
    #     to_status == OrderStatusType.refunded
    # ):
    #     """
    #     Accounting
    #     Wallet
    #     Invoice
    #     Webhook
    #     Email
    #     Notification
    #     ERP
    #     """
    #     pass