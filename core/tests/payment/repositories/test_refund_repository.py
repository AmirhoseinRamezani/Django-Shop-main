from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from payment.enums import RefundStatus
from payment.repositories.refund_repository import RefundRepository
from tests.factories.payment import PaymentFactory, RefundFactory


@pytest.mark.django_db
class TestRefundRepository:
    def test_basic_reads_and_payment_scope(self):
        payment = PaymentFactory(success=True, consumed=True)
        refund = RefundFactory(payment=payment)

        assert RefundRepository.get(refund.pk).pk == refund.pk
        assert RefundRepository.find(refund.pk).pk == refund.pk
        assert RefundRepository.find(-1) is None
        assert list(RefundRepository.for_payment(payment.pk)) == [refund]

    def test_status_queries_and_successful_amount(self):
        payment = PaymentFactory(success=True, consumed=True, amount=Decimal("1000000"))
        successful = RefundFactory(
            payment=payment,
            amount=Decimal("400000"),
            success=True,
        )
        RefundFactory(
            payment=payment,
            amount=Decimal("300000"),
            failed=True,
        )
        pending = RefundFactory(
            payment=payment,
            amount=Decimal("200000"),
        )

        assert list(RefundRepository.successful_for_payment(payment.pk)) == [successful]
        assert list(RefundRepository.failed_for_payment(payment.pk))
        assert list(RefundRepository.pending_for_payment(payment.pk)) == [pending]
        assert RefundRepository.successful_amount_for_payment(payment.pk) == Decimal("400000")
        assert RefundRepository.has_refundable_balance(
            payment_id=payment.pk,
            payment_amount=payment.amount,
        ) is True

    def test_idempotency_key_is_unique(self):
        payment = PaymentFactory(success=True, consumed=True)
        RefundFactory(payment=payment, idempotency_key="refund-key")

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                RefundFactory(payment=payment, idempotency_key="refund-key")

    def test_idempotency_lookup_normalizes_surrounding_whitespace(self):
        payment = PaymentFactory(success=True, consumed=True)
        refund = RefundFactory(payment=payment, idempotency_key="refund-key")

        assert RefundRepository.find_by_idempotency_key(" refund-key ").pk == refund.pk
        with transaction.atomic():
            assert RefundRepository.find_by_idempotency_key_for_update(" refund-key ").pk == refund.pk

    def test_gateway_identity_is_scoped_by_database_payment_constraint(self):
        payment_a = PaymentFactory(success=True, consumed=True)
        payment_b = PaymentFactory(success=True, consumed=True)
        RefundFactory(
            payment=payment_a,
            success=True,
            gateway_reference="REFUND-UNIQUE",
        )

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                RefundFactory(
                    payment=payment_a,
                    gateway_reference="REFUND-UNIQUE",
                    status=RefundStatus.PENDING,
                )

        other = RefundFactory(
            payment=payment_b,
            gateway_reference="REFUND-UNIQUE",
        )
        assert other.payment_id == payment_b.pk

    def test_save_rejects_financial_and_request_identity_fields(self):
        payment = PaymentFactory(success=True, consumed=True)
        refund = RefundFactory(payment=payment)

        for field in (
            "payment",
            "payment_id",
            "amount",
            "currency",
            "idempotency_key",
            "reason",
            "reason_detail",
            "requested_at",
        ):
            with pytest.raises(ValueError):
                RefundRepository.save(refund, update_fields=[field])

    def test_save_rejects_empty_update_fields(self):
        payment = PaymentFactory(success=True, consumed=True)
        refund = RefundFactory(payment=payment)

        with pytest.raises(ValueError, match="at least one update field"):
            RefundRepository.save(refund, update_fields=[])

    def test_locking_variants_are_explicit(self):
        payment = PaymentFactory(success=True, consumed=True)
        refund = RefundFactory(payment=payment)

        with transaction.atomic():
            assert RefundRepository.get_for_update(refund.pk).pk == refund.pk
            assert RefundRepository.find_for_update(refund.pk).pk == refund.pk
            assert RefundRepository.get_for_update_nowait(refund.pk).pk == refund.pk

        queryset = RefundRepository.stale_pending_for_update_skip_locked(
            requested_before=refund.requested_at,
        )
        assert queryset.query.select_for_update is True
        assert queryset.query.select_for_update_skip_locked is True
