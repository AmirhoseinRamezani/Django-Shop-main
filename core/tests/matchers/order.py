# tests/matchers/order.py
from order.models import (
    OrderStatusType,
)


def created(order):

    order.refresh_from_db()

    assert order.pk

    assert (
        order.status
        ==
        OrderStatusType.pending
    )


def paid(order):

    order.refresh_from_db()

    assert (
        order.status
        ==
        OrderStatusType.paid
    )


def cancelled(order):

    order.refresh_from_db()

    assert (
        order.status
        ==
        OrderStatusType.cancelled
    )


def items(order, count):

    assert (
        order.order_items.count()
        ==
        count
    )
