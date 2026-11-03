import pytest

from events.models import OutboxEvent
from order.events.order_event import OrderEvent, OrderEventType
from order.services.events import record_order_event
from tests.factories.order import OrderFactory


@pytest.mark.django_db
def test_record_order_event_persists_domain_and_outbox_identity():
    order = OrderFactory()

    record_order_event(
        order=order,
        type=OrderEventType.CREATED,
        payload={
            "order_id": order.pk + 100,
            "user_id": order.user_id + 100,
            "source": "checkout",
        },
    )

    domain_event = OrderEvent.objects.get(order=order)
    outbox_event = OutboxEvent.objects.get(topic="order.created")

    expected_payload = {
        "order_id": order.pk,
        "user_id": order.user_id,
        "source": "checkout",
    }
    assert domain_event.payload == expected_payload
    assert outbox_event.payload == expected_payload


@pytest.mark.django_db
def test_record_order_event_rolls_back_domain_event_when_outbox_insert_fails(mocker):
    order = OrderFactory()
    mocker.patch(
        "order.services.events.OutboxEvent.objects.create",
        side_effect=RuntimeError("outbox unavailable"),
    )

    with pytest.raises(RuntimeError, match="outbox unavailable"):
        record_order_event(
            order=order,
            type=OrderEventType.CREATED,
        )

    assert not OrderEvent.objects.filter(order=order).exists()
    assert not OutboxEvent.objects.filter(payload__order_id=order.pk).exists()


@pytest.mark.parametrize(
    ("event_type", "expected_topic"),
    [
        (OrderEventType.CREATED, "order.created"),
        (OrderEventType.PENDING, "order.pending"),
        (OrderEventType.PAYMENT_STARTED, "order.payment_started"),
        (OrderEventType.PAID, "order.paid"),
        (OrderEventType.FAILED, "order.failed"),
        (OrderEventType.PROCESSING, "order.processing"),
        (OrderEventType.SHIPPED, "order.shipped"),
        (OrderEventType.DELIVERED, "order.delivered"),
        (OrderEventType.RETURN_REQUESTED, "order.return_requested"),
        (OrderEventType.RETURNED, "order.returned"),
        (OrderEventType.EXPIRED, "order.expired"),
        (OrderEventType.CANCELLED, "order.cancelled"),
        (OrderEventType.REFUNDED, "order.refunded"),
        (OrderEventType.ADMIN_NOTE, "order.admin_note"),
    ],
)
def test_order_event_type_has_explicit_outbox_topic(
    event_type,
    expected_topic,
):
    from order.services.events import _map_order_event_to_topic

    assert _map_order_event_to_topic(event_type) == expected_topic


def test_unknown_order_event_type_is_rejected():
    from order.services.events import _map_order_event_to_topic

    with pytest.raises(ValueError, match="No outbox topic"):
        _map_order_event_to_topic("UNKNOWN")