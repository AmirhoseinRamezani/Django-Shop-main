import pytest
from django.db import IntegrityError, transaction

from payment.enums import PaymentAttemptStatus
from payment.repositories.payment_attempt_repository import PaymentAttemptRepository
from tests.factories.payment import PaymentAttemptFactory, PaymentFactory


@pytest.mark.django_db
class TestPaymentAttemptRepository:
    def test_basic_reads_and_payment_scoping(self, payment):
        attempt = PaymentAttemptFactory(payment=payment)

        assert PaymentAttemptRepository.get(attempt.pk).pk == attempt.pk
        assert PaymentAttemptRepository.find(attempt.pk).pk == attempt.pk
        assert PaymentAttemptRepository.find(-1) is None
        assert list(PaymentAttemptRepository.for_payment(payment.pk)) == [attempt]

    def test_latest_and_first_are_deterministic(self, payment):
        first = PaymentAttemptFactory(payment=payment, failed=True, attempt_number=1)
        second = PaymentAttemptFactory(
            payment=payment,
            success=True,
            attempt_number=2,
            retry_of=first,
            retry_count=2,
        )

        assert PaymentAttemptRepository.first_for_payment(payment.pk).pk == first.pk
        assert PaymentAttemptRepository.latest_for_payment(payment.pk).pk == second.pk
        assert PaymentAttemptRepository.latest_successful_for_payment(payment.pk).pk == second.pk

    def test_attempt_number_is_unique_per_payment(self, payment):
        PaymentAttemptFactory(payment=payment, attempt_number=1)

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                PaymentAttemptFactory(payment=payment, attempt_number=1)

    def test_attempt_number_isolated_between_payments(self):
        payment_a = PaymentFactory()
        payment_b = PaymentFactory()

        first = PaymentAttemptFactory(payment=payment_a, attempt_number=1)
        second = PaymentAttemptFactory(payment=payment_b, attempt_number=1)

        assert first.attempt_number == second.attempt_number == 1

    def test_next_attempt_number_is_informational(self, payment):
        assert PaymentAttemptRepository.next_attempt_number(payment.pk) == 1

        first = PaymentAttemptFactory(payment=payment, attempt_number=1)
        assert PaymentAttemptRepository.next_attempt_number(payment.pk) == 2
        assert PaymentAttemptRepository.last_attempt_number(payment.pk) == 1

        PaymentAttemptFactory(
            payment=payment,
            attempt_number=2,
            retry_of=first,
            retry_count=2,
            failed=True,
        )
        assert PaymentAttemptRepository.next_attempt_number(payment.pk) == 3

    def test_identity_lookups_are_payment_scoped(self):
        payment_a = PaymentFactory()
        payment_b = PaymentFactory()
        attempt = PaymentAttemptFactory(
            payment=payment_a,
            success=True,
            authority_id="AUTH-ISOLATED",
            gateway_reference="REF-ISOLATED",
            gateway_transaction_id="TX-ISOLATED",
        )

        assert PaymentAttemptRepository.find_by_authority(
            payment_id=payment_a.pk,
            authority_id=" AUTH-ISOLATED ",
        ).pk == attempt.pk
        assert PaymentAttemptRepository.find_by_reference(
            payment_id=payment_a.pk,
            gateway_reference=" REF-ISOLATED ",
        ).pk == attempt.pk
        assert PaymentAttemptRepository.find_by_transaction_id(
            payment_id=payment_a.pk,
            gateway_transaction_id=" TX-ISOLATED ",
        ).pk == attempt.pk

        assert PaymentAttemptRepository.find_by_authority(
            payment_id=payment_b.pk,
            authority_id="AUTH-ISOLATED",
        ) is None

    def test_empty_identity_does_not_query_or_resolve(self, payment):
        assert PaymentAttemptRepository.find_by_authority(
            payment_id=payment.pk,
            authority_id="   ",
        ) is None
        assert PaymentAttemptRepository.find_by_reference(
            payment_id=payment.pk,
            gateway_reference="",
        ) is None
        assert PaymentAttemptRepository.find_by_transaction_id(
            payment_id=payment.pk,
            gateway_transaction_id="",
        ) is None

    def test_save_rejects_structural_fields(self, payment):
        attempt = PaymentAttemptFactory(payment=payment)

        for field in ("payment", "payment_id", "attempt_number", "retry_of", "retry_of_id"):
            with pytest.raises(ValueError):
                PaymentAttemptRepository.save(attempt, update_fields=[field])

    def test_save_rejects_empty_update_fields(self, payment):
        attempt = PaymentAttemptFactory(payment=payment)

        with pytest.raises(ValueError, match="at least one update field"):
            PaymentAttemptRepository.save(attempt, update_fields=[])

    def test_locking_variants_are_explicit(self, payment):
        attempt = PaymentAttemptFactory(payment=payment)

        with transaction.atomic():
            assert PaymentAttemptRepository.get_for_update(attempt.pk).pk == attempt.pk
            assert PaymentAttemptRepository.find_for_update(attempt.pk).pk == attempt.pk
            assert PaymentAttemptRepository.get_for_update_nowait(attempt.pk).pk == attempt.pk

        queryset = PaymentAttemptRepository.pending_for_update_skip_locked()
        assert queryset.query.select_for_update is True
        assert queryset.query.select_for_update_skip_locked is True

    def test_terminal_and_pending_queries_are_distinct(self, payment):
        pending = PaymentAttemptFactory(payment=payment, status=PaymentAttemptStatus.PENDING)
        failed = PaymentAttemptFactory(
            payment=payment,
            failed=True,
            attempt_number=2,
            retry_of=pending,
            retry_count=2,
        )

        assert list(PaymentAttemptRepository.pending_for_payment(payment.pk)) == [pending]
        assert list(PaymentAttemptRepository.failed_for_payment(payment.pk)) == [failed]
        assert list(PaymentAttemptRepository.terminal_for_payment(payment.pk)) == [failed]
