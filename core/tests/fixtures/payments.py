# tests/fixtures/payments.py
import pytest

from tests.factories.payment import PaymentFactory

from payment.models import (
    PaymentModel,
)
from payment.enums import (
    PaymentStatusType,
)

@pytest.fixture
def success_payment(order):

    return PaymentModel.objects.create(
        order=order,
        authority_id="AUTH-123",
        amount=order.total_price,
        ref_id=123456,
        status=PaymentStatusType.SUCCESS,
    )
    
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

    return PaymentModel.objects.create(
        order=order,
        authority_id="FAILED",
        amount=order.total_price,
        status=PaymentStatusType.FAILED,
    )

@pytest.fixture
def pending_payment(order):

    return PaymentModel.objects.create(
        order=order,
        authority_id="PENDING",
        amount=order.total_price,
        status=PaymentStatusType.PENDING,
    )

@pytest.fixture
def payment_factory():
    return PaymentFactory


@pytest.fixture
def payment(order):
    return PaymentFactory(order=order)

@pytest.fixture
def successful_payment(order):
    return PaymentFactory(
        order=order,
        success=True,
    )
