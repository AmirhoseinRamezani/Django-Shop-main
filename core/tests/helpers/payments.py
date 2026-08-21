# tests/helpers/payments.py

from payment.enums import (
    PaymentStatusType,
)


def assert_pending(payment):

    payment.refresh_from_db()

    assert (
        payment.status
        ==
        PaymentStatusType.PENDING
    )


def assert_success(payment):

    payment.refresh_from_db()

    assert (
        payment.status
        ==
        PaymentStatusType.SUCCESS
    )


def assert_failed(payment):

    payment.refresh_from_db()

    assert (
        payment.status
        ==
        PaymentStatusType.FAILED
    )
