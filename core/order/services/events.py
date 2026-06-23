# order/services/events.py
from order.events.order_event import OrderEvent
from events.models.outbox import OutboxEvent


def record_order_event(*, order, type, actor=None, payload=None):
    payload = payload or {}
    
    # 1. Domain Event (history)
    OrderEvent.objects.create(
        order=order,
        type=type,
        actor=actor,
        payload=payload,
    )

    # 2. Integration Event (Outbox)
    OutboxEvent.objects.create(
        topic=_map_order_event_to_topic(type),
        payload={
            "order_id": order.id,
            "user_id": order.user_id,
            **payload,
        }
    )

def _map_order_event_to_topic(event_type: str) -> str:
    return {
        "PAID": "order.paid",
        "CREATED": "order.created",
        "CANCELLED": "order.cancelled",
        "EXPIRED": "order.expired",
        "REFUNDED": "order.refunded",
    }.get(event_type, "order.unknown")