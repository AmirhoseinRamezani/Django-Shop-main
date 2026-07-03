# tests/helpers/orders.py
from order.models import OrderStatusType


def assert_pending(order):

    order.refresh_from_db()

    assert order.status == OrderStatusType.pending


def assert_paid(order):

    order.refresh_from_db()

    assert order.status == OrderStatusType.paid


def assert_processing(order):

    order.refresh_from_db()

    assert order.status == OrderStatusType.processing


def assert_cancelled(order):

    order.refresh_from_db()

    assert order.status == OrderStatusType.cancelled
