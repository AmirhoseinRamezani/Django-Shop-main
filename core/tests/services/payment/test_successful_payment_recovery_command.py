from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from payment.enums import PaymentStatusType
from payment.models import (
    PaymentModel,
    PaymentResolution,
    PaymentResolutionReason,
)
from tests.factories.payment import PaymentFactory


pytestmark = pytest.mark.django_db(transaction=True)


COMMAND_PATH = (
    "payment.management.commands."
    "reconcile_successful_payments.synchronize_successful_payment"
)


def test_command_recovers_only_successful_unconsumed_payments(capsys):
    eligible = PaymentFactory(
        status=PaymentStatusType.SUCCESS,
        is_consumed=False,
    )

    already_consumed = PaymentFactory(
        status=PaymentStatusType.SUCCESS,
        is_consumed=True,
    )

    pending = PaymentFactory(
        status=PaymentStatusType.PENDING,
        is_consumed=False,
    )

    resolved = PaymentFactory(
        status=PaymentStatusType.SUCCESS,
        is_consumed=False,
    )

    PaymentResolution.objects.create(
        payment=resolved,
        reason=PaymentResolutionReason.ORDER_CANCELLED,
        order_status_at_detection="cancelled",
    )

    with patch(
        COMMAND_PATH,
        return_value=SimpleNamespace(is_consumed=True),
    ) as synchronize:
        call_command("reconcile_successful_payments")

    synchronize.assert_called_once_with(payment_id=eligible.pk)

    output = capsys.readouterr().out

    assert "recovered=1" in output
    assert "skipped=0" in output
    assert "errors=0" in output

    assert PaymentModel.objects.filter(
        pk=already_consumed.pk,
        is_consumed=True,
    ).exists()

    assert PaymentModel.objects.filter(
        pk=pending.pk,
        status=PaymentStatusType.PENDING,
    ).exists()


def test_command_dry_run_does_not_synchronize_payments(capsys):
    payment = PaymentFactory(
        status=PaymentStatusType.SUCCESS,
        is_consumed=False,
    )

    with patch(COMMAND_PATH) as synchronize:
        call_command("reconcile_successful_payments", "--dry-run")

    synchronize.assert_not_called()

    output = capsys.readouterr().out
    assert "Dry run: 1" in output

    payment.refresh_from_db()
    assert payment.is_consumed is False


def test_command_continues_after_individual_recovery_failure(capsys):
    PaymentFactory(
        status=PaymentStatusType.SUCCESS,
        is_consumed=False,
    )
    PaymentFactory(
        status=PaymentStatusType.SUCCESS,
        is_consumed=False,
    )

    with patch(
        COMMAND_PATH,
        side_effect=[
            RuntimeError("simulated recovery failure"),
            SimpleNamespace(is_consumed=True),
        ],
    ) as synchronize:
        call_command("reconcile_successful_payments")

    assert synchronize.call_count == 2

    captured = capsys.readouterr()

    assert "recovered=1" in captured.out
    assert "errors=1" in captured.out
    assert "RuntimeError" in captured.err


def test_command_rejects_non_positive_limit():
    with pytest.raises(CommandError, match="greater than zero"):
        call_command(
            "reconcile_successful_payments",
            limit=0,
        )