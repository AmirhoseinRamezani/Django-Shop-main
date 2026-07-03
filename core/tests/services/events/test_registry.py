# tests/services/events/test_registry.py
from events.dispatchers.registry import ROUTES


def test_required_topics_registered():

    required = {
        "user.otp",
        "order.created",
        "order.paid",
        "coupon.used",
    }

    assert required.issubset(
        ROUTES.keys()
    )