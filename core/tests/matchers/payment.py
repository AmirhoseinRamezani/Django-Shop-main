# tests/matchers/payment.py
from payment.enums import (
    PaymentStatusType,
)

def pending(payment):

    payment.refresh_from_db()

    assert (
        payment.status
        ==
        PaymentStatusType.PENDING
    )


def success(payment):

    payment.refresh_from_db()

    assert (
        payment.status
        ==
        PaymentStatusType.SUCCESS
    )


def consumed(payment):

    payment.refresh_from_db()

    assert payment.is_consumed
