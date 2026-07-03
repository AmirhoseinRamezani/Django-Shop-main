# tests/helpers/payments.py

from payment.models import (
    PaymentStatusType,
)


def assert_pending(payment):

    payment.refresh_from_db()

    assert (
        payment.status
        ==
        PaymentStatusType.pending
    )


def assert_success(payment):

    payment.refresh_from_db()

    assert (
        payment.status
        ==
        PaymentStatusType.success
    )


def assert_failed(payment):

    payment.refresh_from_db()

    assert (
        payment.status
        ==
        PaymentStatusType.failed
    )
