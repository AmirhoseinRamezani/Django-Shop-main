from order.events.order_event import OrderEvent


def record_order_event(*, order, type, actor=None, payload=None):
    OrderEvent.objects.create(
        order=order,
        type=type,
        actor=actor,
        payload=payload or {},
    )
