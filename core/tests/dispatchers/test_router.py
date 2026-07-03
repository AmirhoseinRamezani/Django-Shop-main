# tests/dispatchers/test_router.py
import pytest

from events.dispatchers.router import dispatch


pytestmark = pytest.mark.django_db


class DummyEvent:

    def __init__(self, topic):
        self.topic = topic
        self.payload = {}


def test_order_paid_route(mocker):

    email = mocker.patch(
        "events.dispatchers.router.ROUTES['order.paid'][0]"
    )

    telegram = mocker.patch(
        "events.dispatchers.router.ROUTES['order.paid'][1]"
    )

    webhook = mocker.patch(
        "events.dispatchers.router.ROUTES['order.paid'][2]"
    )

    dispatch(DummyEvent("order.paid"))

    email.assert_called_once()
    telegram.assert_called_once()
    webhook.assert_called_once()


def test_unknown_topic():

    dispatch(DummyEvent("unknown.topic"))