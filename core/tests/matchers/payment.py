# tests/matchers/payment.py
from payment.models import (
    PaymentStatusType,
)


def pending(payment):

    payment.refresh_from_db()

    assert (
        payment.status
        ==
        PaymentStatusType.pending
    )


def success(payment):

    payment.refresh_from_db()

    assert (
        payment.status
        ==
        PaymentStatusType.success
    )


def consumed(payment):

    payment.refresh_from_db()

    assert payment.is_consumed
