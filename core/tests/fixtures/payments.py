# tests/fixtures/payments.py
import pytest

from tests.factories.payment import PaymentAttemptFactory ,PaymentFactory

from payment.models import (
    PaymentModel,
)
from payment.enums import (
    PaymentStatusType,
    PaymentAttemptStatus,
)

@pytest.fixture
def success_payment(order):

    payment = PaymentFactory(
        order=order,
        success=True,
    )

    PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        status=PaymentAttemptStatus.SUCCESS,
        authority_id="AUTH-123",
        gateway_reference="REF-123",
        gateway_transaction_id="123456",
    )

    return payment
    
@pytest.fixture
def consumed_payment(
    success_payment,
):
    success_payment.is_consumed = True
    success_payment.save(
        update_fields=["is_consumed"]
    )

    return success_payment

@pytest.fixture
def failed_payment(order):

    payment = PaymentFactory(
        order=order,
        failed=True,
    )

    PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        status=PaymentAttemptStatus.FAILED,
        authority_id="FAILED",
    )

    return payment

@pytest.fixture
def pending_payment(order):

    payment = PaymentFactory(
        order=order,
        amount=order.total_price,
    )

    PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        status=PaymentAttemptStatus.PENDING,
        authority_id="PENDING",
    )

    return payment
        

@pytest.fixture
def payment_factory():
    return PaymentFactory


@pytest.fixture
def payment(order):
    payment = PaymentFactory(
        order=order,
        # amount=order.total_price,
    )

    PaymentAttemptFactory(
        payment=payment,
        status=PaymentAttemptStatus.PENDING,
    )

    return payment

@pytest.fixture
def successful_payment(order):
    
    payment = PaymentFactory(
        order=order,
    )

    PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        status=PaymentAttemptStatus.SUCCESS,
        authority_id="SUCCESS",
    )

    return payment