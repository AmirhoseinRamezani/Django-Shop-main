# tests/assertions.py

from order.models import OrderStatusType
from payment.enums import PaymentStatusType
from events.models import OutboxStatus


# --------------------------------------------------
# refresh
# --------------------------------------------------

def refresh(*objects):
    for obj in objects:
        if obj is not None:
            obj.refresh_from_db()


# --------------------------------------------------
# Orders
# --------------------------------------------------

def assert_order_created(order):
    refresh(order)

    assert order.pk is not None
    assert order.status == OrderStatusType.pending


def assert_order_paid(order):
    refresh(order)

    assert order.status == OrderStatusType.paid


def assert_order_cancelled(order):
    refresh(order)

    assert order.status == OrderStatusType.cancelled


def assert_order_item_created(order, count=1):
    assert order.order_items.count() == count


# --------------------------------------------------
# Payment
# --------------------------------------------------

def assert_payment_pending(payment):
    refresh(payment)

    assert payment.status == PaymentStatusType.PENDING


def assert_payment_success(payment):
    refresh(payment)

    assert payment.status == PaymentStatusType.SUCCESS


def assert_payment_failed(payment):
    refresh(payment)

    assert payment.status == PaymentStatusType.FAILED


def assert_payment_consumed(payment):
    refresh(payment)

    assert payment.is_consumed


# --------------------------------------------------
# Coupon
# --------------------------------------------------

def assert_coupon_used(coupon, count=1):
    refresh(coupon)

    assert coupon.used_count == count


# --------------------------------------------------
# Stock
# --------------------------------------------------

def assert_stock_decreased(
    product,
    old_stock,
    quantity,
):
    refresh(product)

    assert product.stock == old_stock - quantity


def assert_stock_restored(
    product,
    old_stock,
):
    refresh(product)

    assert product.stock == old_stock


# --------------------------------------------------
# Outbox
# --------------------------------------------------

def assert_processed(event):
    refresh(event)

    assert event.status == OutboxStatus.processed


def assert_pending(event):
    refresh(event)

    assert event.status == OutboxStatus.pending


def assert_failed(event):
    refresh(event)

    assert event.status == OutboxStatus.failed



# from events.models import OutboxStatus
def assert_event_pending(event):

    event.refresh_from_db()

    assert (
        event.status ==
        OutboxStatus.pending
    )



def assert_event_processed(event):

    event.refresh_from_db()

    assert (
        event.status ==
        OutboxStatus.processed
    )



def assert_event_failed(event):

    event.refresh_from_db()

    assert (
        event.status ==
        OutboxStatus.failed
    )



def assert_event_retry_count(
        event,
        expected
):

    event.refresh_from_db()

    assert (
        event.retry_count ==
        expected
    )