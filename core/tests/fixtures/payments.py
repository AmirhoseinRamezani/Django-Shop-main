# tests/fixtures/payments.py
from __future__ import annotations

import pytest

from payment.enums import (
    PaymentAttemptStatus,
    PaymentStatusType,
)
from payment.models import PaymentModel
from tests.factories.payment import (
    PaymentAttemptFactory,
    PaymentFactory,
)


def _delete_attempts(payment):
    payment.attempts.all().delete()


def _create_attempt(
    payment,
    *,
    status,
    authority_id,
    gateway_reference="REF-TEST",
    gateway_transaction_id="TXN-TEST",
):
    return PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        status=status,
        authority_id=authority_id,
        gateway_reference=gateway_reference,
        gateway_transaction_id=gateway_transaction_id,
        response_code="100",
        gateway_message="Payment successful",
    )


@pytest.fixture
def success_payment(order):
    payment = PaymentFactory(
        order=order,
        status=PaymentStatusType.SUCCESS,
    )

    _delete_attempts(payment)

    _create_attempt(
        payment,
        status=PaymentAttemptStatus.SUCCESS,
        authority_id="AUTH-123",
        gateway_reference="REF-123456",
        gateway_transaction_id="TXN-123456",
    )

    return payment


@pytest.fixture
def consumed_payment(
    success_payment,
):
    success_payment.is_consumed = True

    success_payment.save(
        update_fields=[
            "is_consumed",
        ],
    )

    return success_payment


@pytest.fixture
def failed_payment(order):
    payment = PaymentFactory(
        order=order,
        status=PaymentStatusType.FAILED,
    )

    _delete_attempts(payment)

    return payment


@pytest.fixture
def pending_payment(order):
    payment = PaymentFactory(
        order=order,
        status=PaymentStatusType.PENDING,
    )

    _delete_attempts(payment)

    _create_attempt(
        payment,
        status=PaymentAttemptStatus.PENDING,
        authority_id="AUTH-PENDING",
    )

    return payment


@pytest.fixture
def payment_factory():
    return PaymentFactory


@pytest.fixture
def payment(order):
    return PaymentFactory(
        order=order,
    )


@pytest.fixture
def successful_payment(order):
    payment = PaymentFactory(
        order=order,
        status=PaymentStatusType.SUCCESS,
    )

    _delete_attempts(payment)

    _create_attempt(
        payment,
        status=PaymentAttemptStatus.SUCCESS,
        authority_id="AUTH-SUCCESSFUL",
        gateway_reference="REF-SUCCESSFUL",
        gateway_transaction_id="TXN-SUCCESSFUL",
    )

    return payment