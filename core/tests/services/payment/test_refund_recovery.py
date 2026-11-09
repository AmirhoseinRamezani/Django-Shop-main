from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from order.models import OrderStatusType
from payment.enums import PaymentStatusType, RefundStatus
from payment.exceptions import PaymentGatewayNotSupportedError
from payment.repositories.refund_recovery_lock_repository import (
    RefundRecoveryLockRepository,
)
from payment.services.refund import RefundService
from payment.services.refund_recovery import RefundRecoveryWorker
from tests.factories.payment import (
    PaymentAttemptFactory,
    PaymentFactory,
    RefundFactory,
)

pytestmark = pytest.mark.django_db


def _payment():
    payment = PaymentFactory(
        order__status=OrderStatusType.paid,
        order__paid_date=timezone.now(),
        order__total_price=Decimal("1000000"),
        order__subtotal_price=Decimal("1000000"),
        order__payable_price=Decimal("1000000"),
        amount=Decimal("1000000"),
        status=PaymentStatusType.SUCCESS,
        is_consumed=True,
        is_refunded=False,
    )
    PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        success=True,
    )
    return payment


@contextmanager
def _acquired_lock(refund_id):
    yield True


@contextmanager
def _busy_lock(refund_id):
    yield False


def test_refund_recovery_worker_processes_only_one_bounded_stale_batch(monkeypatch):
    payment = _payment()
    stale = [
        RefundFactory(
            payment=payment,
            amount=Decimal("100000"),
            status=RefundStatus.PENDING,
        )
        for _ in range(3)
    ]
    monkeypatch.setattr(
        RefundRecoveryLockRepository,
        "hold",
        _acquired_lock,
    )
    reconcile = Mock(
        side_effect=lambda *, refund_id: SimpleNamespace(
            status=RefundStatus.SUCCESS,
        )
    )
    monkeypatch.setattr(
        RefundService,
        "reconcile_pending_refund",
        reconcile,
    )

    report = RefundRecoveryWorker.run_batch(
        batch_size=2,
        older_than=timedelta(minutes=30),
        now=timezone.now() + timedelta(hours=1),
    )

    assert report.examined == 2
    assert report.succeeded == 2
    assert report.errors == 0
    assert reconcile.call_count == 2
    assert {call.kwargs["refund_id"] for call in reconcile.call_args_list}.issubset(
        {refund.pk for refund in stale}
    )



def test_refund_recovery_worker_skips_refund_owned_by_another_worker(monkeypatch):
    payment = _payment()
    RefundFactory(
        payment=payment,
        amount=Decimal("100000"),
        status=RefundStatus.PENDING,
    )
    monkeypatch.setattr(
        RefundRecoveryLockRepository,
        "hold",
        _busy_lock,
    )
    reconcile = Mock()
    monkeypatch.setattr(
        RefundService,
        "reconcile_pending_refund",
        reconcile,
    )

    report = RefundRecoveryWorker.run_batch(
        batch_size=10,
        older_than=timedelta(minutes=30),
        now=timezone.now() + timedelta(hours=1),
    )

    assert report.examined == 1
    assert report.skipped_locked == 1
    reconcile.assert_not_called()

def test_refund_recovery_worker_isolates_per_record_failure(monkeypatch):
    payment = _payment()
    refunds = [
        RefundFactory(
            payment=payment,
            amount=Decimal("100000"),
            status=RefundStatus.PENDING,
        )
        for _ in range(2)
    ]
    monkeypatch.setattr(
        RefundRecoveryLockRepository,
        "hold",
        _acquired_lock,
    )

    def reconcile(*, refund_id):
        if refund_id == refunds[0].pk:
            raise RuntimeError("simulated reconciliation failure")
        return Mock(status=RefundStatus.SUCCESS)

    monkeypatch.setattr(
        RefundService,
        "reconcile_pending_refund",
        reconcile,
    )

    report = RefundRecoveryWorker.run_batch(
        batch_size=2,
        older_than=timedelta(minutes=30),
        now=timezone.now() + timedelta(hours=1),
    )

    assert report.examined == 2
    assert report.errors == 1
    assert report.succeeded == 1


def test_refund_recovery_worker_reports_unsupported_provider_without_mutation(
    monkeypatch,
):
    payment = _payment()
    refund = RefundFactory(
        payment=payment,
        amount=Decimal("100000"),
        status=RefundStatus.PENDING,
    )
    monkeypatch.setattr(
        RefundRecoveryLockRepository,
        "hold",
        _acquired_lock,
    )
    monkeypatch.setattr(
        RefundService,
        "reconcile_pending_refund",
        Mock(side_effect=PaymentGatewayNotSupportedError("inquiry unsupported")),
    )

    report = RefundRecoveryWorker.run_batch(
        batch_size=10,
        older_than=timedelta(minutes=30),
        now=timezone.now() + timedelta(hours=1),
    )

    refund.refresh_from_db()
    assert report.unsupported == 1
    assert report.errors == 0
    assert refund.status == RefundStatus.PENDING
    assert refund.finished_at is None


def test_refund_recovery_command_returns_nonzero_for_unsupported_provider(
    monkeypatch,
):
    monkeypatch.setattr(
        "payment.management.commands.recover_pending_refunds.RefundRecoveryWorker.run_batch",
        lambda **kwargs: Mock(
            examined=1,
            succeeded=0,
            failed=0,
            unresolved=0,
            unsupported=1,
            skipped_locked=0,
            errors=0,
            has_operational_failures=True,
        ),
    )

    with pytest.raises(CommandError):
        call_command("recover_pending_refunds")
