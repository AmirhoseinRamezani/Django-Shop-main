# tests/services/payment/test_payment_resolution_recovery.py
from io import StringIO

import pytest
from django.core.management import call_command, CommandError

from payment.enums import PaymentStatusType
from payment.models import PaymentResolution, PaymentResolutionReason, PaymentResolutionStatus
from tests.factories.order import OrderFactory
from tests.factories.payment import PaymentFactory, PaymentAttemptFactory

pytestmark = [pytest.mark.django_db, pytest.mark.service]


def _cancelled_successful_payment():
    order = OrderFactory(cancelled=True)
    payment = PaymentFactory(order=order, status=PaymentStatusType.SUCCESS, is_consumed=False)
    PaymentAttemptFactory(payment=payment, success=True)
    return payment


def test_recovery_keyset_pagination_processes_records_beyond_first_batch():
    first = _cancelled_successful_payment()
    second = _cancelled_successful_payment()
    output = StringIO()

    call_command("recover_payment_resolutions", batch_size=1, stdout=output, stderr=StringIO())

    assert PaymentResolution.objects.filter(payment_id__in=(first.pk, second.pk)).count() == 2
    assert "examined=2" in output.getvalue()
    assert "open_resolutions=2" in output.getvalue()
    assert PaymentResolution.objects.get(payment=first).reason == PaymentResolutionReason.ORDER_CANCELLED
    assert PaymentResolution.objects.get(payment=second).reason == PaymentResolutionReason.ORDER_CANCELLED


def test_recovery_continues_after_one_candidate_raises(monkeypatch):
    first = _cancelled_successful_payment()
    second = _cancelled_successful_payment()
    from payment.services.verify import synchronize_successful_payment as original

    def fail_first(*, payment_id):
        if payment_id == first.pk:
            raise RuntimeError("synthetic transient failure")
        return original(payment_id=payment_id)

    monkeypatch.setattr(
        "payment.management.commands.recover_payment_resolutions.synchronize_successful_payment",
        fail_first,
    )
    output = StringIO()
    errors = StringIO()
    with pytest.raises(CommandError, match="completed with 1 error"):
        call_command("recover_payment_resolutions", batch_size=1, stdout=output, stderr=errors)

    assert not PaymentResolution.objects.filter(payment=first).exists()
    assert PaymentResolution.objects.filter(payment=second).exists()
    assert "examined=2" in output.getvalue()
    assert "errors=1" in output.getvalue()


def test_recovery_rerun_is_idempotent_and_never_calls_gateway():
    payment = _cancelled_successful_payment()
    output = StringIO()
    call_command(
        "recover_payment_resolutions",
        batch_size=1,
        stdout=output,
        stderr=StringIO(),
    )
    first = PaymentResolution.objects.get(payment=payment)
    first_id = first.pk

    from unittest.mock import patch

    with (
        patch("payment.services.verify.GatewayService.verify", side_effect=AssertionError("gateway must not run")) as verify,
        patch("payment.services.reconciliation.GatewayService.inquire", side_effect=AssertionError("gateway must not run")) as inquire,
    ):
        call_command(
            "recover_payment_resolutions",
            batch_size=1,
            stdout=StringIO(),
            stderr=StringIO(),
        )

    first.refresh_from_db()
    assert first.pk == first_id
    assert first.status == PaymentResolutionStatus.OPEN
    assert PaymentResolution.objects.filter(payment=payment).count() == 1
    verify.assert_not_called()
    inquire.assert_not_called()


def test_recovery_finishes_payment_after_success_persisted_before_order_finalization(monkeypatch):
    """A process failure after gateway success must remain recoverable without re-verification."""
    from payment.services.verify import synchronize_successful_payment

    payment = PaymentFactory(status=PaymentStatusType.SUCCESS, is_consumed=False)
    PaymentAttemptFactory(payment=payment, success=True)
    original_confirm = __import__(
        "payment.services.verify", fromlist=["confirm_order_payment"]
    ).confirm_order_payment

    def crash_after_success(*, order_id, payment_id):
        raise RuntimeError("simulated process failure before finalization")

    monkeypatch.setattr(
        "payment.services.verify.confirm_order_payment",
        crash_after_success,
    )

    with pytest.raises(RuntimeError, match="simulated process failure"):
        synchronize_successful_payment(payment_id=payment.pk)

    payment.refresh_from_db()
    assert payment.status == PaymentStatusType.SUCCESS
    assert payment.is_consumed is False

    monkeypatch.setattr(
        "payment.services.verify.confirm_order_payment",
        original_confirm,
    )

    recovered = synchronize_successful_payment(payment_id=payment.pk)

    payment.refresh_from_db()
    payment.order.refresh_from_db()
    assert recovered.pk == payment.pk
    assert payment.is_consumed is True
    assert payment.order.is_paid
