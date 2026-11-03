# order/services/events.py
from django.db import transaction

from order.events.order_event import OrderEvent, OrderEventType
from events.models.outbox import OutboxEvent


@transaction.atomic
def record_order_event(*, order, type, actor=None, payload=None):
    """Persist the domain event and its outbox message atomically."""
    event_payload = {
        **(payload or {}),
        # Aggregate identity is authoritative; caller data cannot override it.
        "order_id": order.pk,
        "user_id": order.user_id,
    }

    OrderEvent.objects.create(
        order=order,
        type=type,
        actor=actor,
        payload=event_payload,
    )

    OutboxEvent.objects.create(
        topic=_map_order_event_to_topic(type),
        payload=event_payload,
    )

def _map_order_event_to_topic(event_type: str) -> str:
    topics = {
        OrderEventType.CREATED: "order.created",
        OrderEventType.PENDING: "order.pending",
        OrderEventType.PAYMENT_STARTED: "order.payment_started",
        OrderEventType.PAID: "order.paid",
        OrderEventType.FAILED: "order.failed",
        OrderEventType.PROCESSING: "order.processing",
        OrderEventType.SHIPPED: "order.shipped",
        OrderEventType.DELIVERED: "order.delivered",
        OrderEventType.RETURN_REQUESTED: "order.return_requested",
        OrderEventType.RETURNED: "order.returned",
        OrderEventType.EXPIRED: "order.expired",
        OrderEventType.CANCELLED: "order.cancelled",
        OrderEventType.REFUNDED: "order.refunded",
        OrderEventType.ADMIN_NOTE: "order.admin_note",
    }

    try:
        return topics[event_type]
    except KeyError as exc:
        raise ValueError(
            f"No outbox topic is defined for OrderEventType {event_type!r}."
        ) from exc