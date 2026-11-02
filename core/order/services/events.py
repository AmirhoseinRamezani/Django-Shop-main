# order/services/events.py
from django.db import transaction

from order.events.order_event import OrderEvent
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
    return {
        "PAID": "order.paid",
        "CREATED": "order.created",
        "CANCELLED": "order.cancelled",
        "EXPIRED": "order.expired",
        "REFUNDED": "order.refunded",
    }.get(event_type, "order.unknown")