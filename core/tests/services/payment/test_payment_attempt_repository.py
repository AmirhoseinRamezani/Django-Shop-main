# tests/services/payment/test_payment_attempt_repository.py
import pytest
from django.core.exceptions import ValidationError

from payment.enums import PaymentAttemptStatus
from payment.repositories.payment_attempt_repository import (
    PaymentAttemptRepository,
)
from tests.factories.payment import PaymentFactory


@pytest.mark.django_db
class TestPaymentAttemptRepositoryPersistence:

    def test_create_validates_domain_invariants_before_insert(self):
        payment = PaymentFactory.create()

        with pytest.raises(ValidationError):
            PaymentAttemptRepository.create(
                payment=payment,
                attempt_number=1,
                retry_count=1,
                status=PaymentAttemptStatus.SUCCESS,
            )

        assert not PaymentAttemptRepository.model.objects.filter(
            payment=payment,
        ).exists()

    def test_create_rejects_cross_payment_retry(self):
        source_payment = PaymentFactory.create()
        target_payment = PaymentFactory.create()

        source = PaymentAttemptRepository.create(
            payment=source_payment,
            attempt_number=1,
            retry_count=1,
            status=PaymentAttemptStatus.PENDING,
        )

        with pytest.raises(ValidationError):
            PaymentAttemptRepository.create(
                payment=target_payment,
                attempt_number=2,
                retry_count=2,
                retry_of=source,
                status=PaymentAttemptStatus.PENDING,
            )

        assert PaymentAttemptRepository.for_payment(
            target_payment.pk,
        ).count() == 0

    def test_save_revalidates_domain_state_before_update(self):
        from tests.factories.payment import PaymentAttemptFactory

        attempt = PaymentAttemptFactory.create()

        attempt.status = PaymentAttemptStatus.SUCCESS
        attempt.finished_at = None

        with pytest.raises(ValidationError):
            PaymentAttemptRepository.save(
                attempt,
                update_fields=(
                    "status",
                    "finished_at",
                ),
            )

        persisted = PaymentAttemptRepository.get(
            attempt.pk,
        )

        assert persisted.status == PaymentAttemptStatus.PENDING
        assert persisted.finished_at is None