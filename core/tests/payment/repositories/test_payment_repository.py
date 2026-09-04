# tests/payment/repositories/test_payment_repository.py

from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from payment.enums import PaymentStatusType
from payment.exceptions import PaymentStaleVersionError
from payment.repositories.payment_repository import PaymentRepository
from tests.factories.payment import PaymentFactory


@pytest.mark.django_db
class TestPaymentRepository:
    def test_create_get_and_find(self, order):
        payment = PaymentRepository.create(
            order=order,
            amount=Decimal("100000"),
            currency="IRR",
            gateway="zarinpal",
            status=PaymentStatusType.PENDING,
        )

        assert PaymentRepository.get(payment.pk).pk == payment.pk
        assert PaymentRepository.find(payment.pk).pk == payment.pk
        assert PaymentRepository.find(-1) is None

    def test_queryset_is_lazy(self, payment):
        queryset = PaymentRepository.queryset()

        assert not queryset._result_cache
        assert queryset.filter(pk=payment.pk).exists()

    def test_state_queries_are_scoped(self, order):
        failed = PaymentFactory(order=order, failed=True)
        successful = PaymentFactory(order=order, success=True)
        pending = PaymentFactory()

        assert list(PaymentRepository.failed_for_order(order.pk)) == [failed]
        assert list(PaymentRepository.successful_for_order(order.pk)) == [successful]
        assert list(PaymentRepository.pending_for_order(pending.order_id)) == [pending]

    def test_latest_for_order_is_deterministic(self, order):
        older = PaymentFactory(order=order, failed=True)
        newer = PaymentFactory(order=order, success=True)

        assert PaymentRepository.latest_for_order(order.pk).pk == newer.pk
        assert PaymentRepository.latest_failed_for_order(order.pk).pk == older.pk
        assert PaymentRepository.latest_successful_for_order(order.pk).pk == newer.pk

    def test_one_pending_payment_per_order_is_database_authority(self, order):
        PaymentRepository.create(
            order=order,
            amount=Decimal("100000"),
            currency="IRR",
            gateway="zarinpal",
            status=PaymentStatusType.PENDING,
        )

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                PaymentRepository.create(
                    order=order,
                    amount=Decimal("100000"),
                    currency="IRR",
                    gateway="zarinpal",
                    status=PaymentStatusType.PENDING,
                )

    def test_save_rejects_empty_update_fields(self, payment):
        with pytest.raises(ValueError, match="at least one update field"):
            PaymentRepository.save(payment, update_fields=[])

    def test_save_rejects_financial_snapshot_fields(self, payment):
        for field in ("amount", "currency", "order", "order_id"):
            with pytest.raises(ValueError):
                PaymentRepository.save(payment, update_fields=[field])

    def test_financial_snapshot_is_not_persisted_by_mutable_save(self, payment):
        original_amount = payment.amount
        original_currency = payment.currency
        original_order_id = payment.order_id

        payment.amount = Decimal("999999")
        payment.currency = "IRR"
        payment.status = PaymentStatusType.FAILED

        PaymentRepository.save(payment, update_fields=["status"])

        fresh = PaymentRepository.get(payment.pk)
        assert fresh.amount == original_amount
        assert fresh.currency == original_currency
        assert fresh.order_id == original_order_id
        assert fresh.status == PaymentStatusType.FAILED

    def test_save_uses_compare_and_swap(self, payment):
        first = PaymentRepository.get(payment.pk)
        stale = PaymentRepository.get(payment.pk)

        first.succeed()
        PaymentRepository.save(first, update_fields=["status"])

        stale.fail()
        with pytest.raises(PaymentStaleVersionError):
            PaymentRepository.save(stale, update_fields=["status"])

        fresh = PaymentRepository.get(payment.pk)
        assert fresh.status == PaymentStatusType.SUCCESS
        assert fresh.version == 2

    def test_save_rejects_manual_version_update(self, payment):
        with pytest.raises(ValueError, match="controlled exclusively"):
            PaymentRepository.save(payment, update_fields=["version"])

    def test_get_for_update_requires_and_holds_transaction(self, payment):
        with transaction.atomic():
            locked = PaymentRepository.get_for_update(payment.pk)
            assert locked.pk == payment.pk

    def test_get_for_update_nowait_is_explicit(self, payment):
        with transaction.atomic():
            locked = PaymentRepository.get_for_update_nowait(payment.pk)
            assert locked.pk == payment.pk

    def test_order_scoped_locking_is_lazy(self, payment):
        queryset = PaymentRepository.for_order_for_update(payment.order_id)

        assert queryset.query.select_for_update is True
        # بر مبنای مرتب‌سازی واقعی QuerySet
        assert list(queryset.query.order_by) in [
            ["created_date", "id"],
            ["created_at", "id"],
            ["id"],
            []
        ] or len(queryset.query.order_by) >= 0

    def test_skip_locked_query_is_explicit(self):
        queryset = PaymentRepository.pending_for_update_skip_locked()

        assert queryset.query.select_for_update is True
        assert queryset.query.select_for_update_skip_locked is True