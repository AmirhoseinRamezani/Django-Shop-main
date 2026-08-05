# tests/fixtures/payments.py

import pytest

from tests.factories.payment import PaymentFactory

from payment.models import (
    PaymentModel,
    PaymentStatusType,
)

@pytest.fixture
def success_payment(order):

    return PaymentModel.objects.create(
        order=order,
        authority_id="AUTH-123",
        amount=order.total_price,
        ref_id=123456,
        status=PaymentStatusType.success,
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
        status=PaymentStatusType.failed,
    )

@pytest.fixture
def pending_payment(order):

    return PaymentModel.objects.create(
        order=order,
        authority_id="PENDING",
        amount=order.total_price,
        status=PaymentStatusType.pending,
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


# @pytest.fixture
# def failed_payment(order):
#     return PaymentFactory(
#         order=order,
#         failed=True,
#     )


# @pytest.fixture
# def consumed_payment(order):
#     return PaymentFactory(
#         order=order,
#         consumed=True,
#     )
    
# @pytest.fixture
# def refunded_payment(
#     success_payment,
# ):
#     success_payment.status = PaymentStatusType.refunded
#     success_payment.is_refunded = True

#     success_payment.save(
#         update_fields=[
#             "status",
#             "is_refunded",
#         ]
#     )

#     return success_payment