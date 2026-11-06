import pytest
from django.core.exceptions import ValidationError

from payment.enums import PaymentStatusType
from payment.repositories.payment_repository import PaymentRepository
from tests.factories.payment import PaymentFactory


pytestmark = pytest.mark.django_db(transaction=True)


def test_existing_payment_instance_cannot_bypass_repository_write_boundary():
    payment = PaymentFactory(success=True)
    original_amount = payment.amount
    original_version = payment.version

    # Attempt to rewrite both immutable financial data and terminal state.
    payment.amount += 1
    payment.status = PaymentStatusType.PENDING

    with pytest.raises(
        ValidationError,
        match="PaymentRepository.save",
    ):
        payment.save(
            update_fields=("amount", "status"),
        )

    persisted = PaymentRepository.get(payment.pk)

    assert persisted.amount == original_amount
    assert persisted.status == PaymentStatusType.SUCCESS
    assert persisted.version == original_version