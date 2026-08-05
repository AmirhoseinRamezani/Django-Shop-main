# tests/dispatchers/test_router.py

import pytest

import events.dispatchers.router as router
from events.dispatchers.router import dispatch


pytestmark = pytest.mark.django_db


class DummyEvent:

    def __init__(self, topic):
        self.topic = topic
        self.payload = {}


def test_order_paid_route(mocker):

    email = mocker.Mock()
    telegram = mocker.Mock()
    webhook = mocker.Mock()

    old_routes = router.ROUTES.copy()

    router.ROUTES["order.paid"] = (
        email,
        telegram,
        webhook,
    )

    try:
        dispatch(DummyEvent("order.paid"))
    finally:
        router.ROUTES = old_routes

    email.assert_called_once()
    telegram.assert_called_once()
    webhook.assert_called_once()


def test_unknown_topic():
    dispatch(DummyEvent("unknown.topic"))