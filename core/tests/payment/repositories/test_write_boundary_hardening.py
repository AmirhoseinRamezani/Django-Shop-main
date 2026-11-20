"""Write-boundary regression tests for lifecycle and identity persistence."""

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from order.models import OrderStatusType
from order.services.inventory import InventoryService
from order.services.state_machine import OrderStateMachine
from payment.managers import _PAYMENT_CORE_REPOSITORY_WRITE_TOKEN
from payment.enums import PaymentAttemptStatus, PaymentStatusType, RefundStatus
from payment.exceptions import (
    PaymentAttemptIdentityConflictError,
    PaymentAttemptInvalidTransitionError,
    PaymentConcurrencyError,
    PaymentGatewayIdentityConflictError,
    PaymentInvalidTransitionError,
)
from payment.repositories.payment_attempt_repository import PaymentAttemptRepository
from payment.repositories.payment_repository import PaymentRepository
from payment.repositories.refund_repository import RefundRepository
from tests.factories.order import OrderFactory
from tests.factories.payment import PaymentAttemptFactory, PaymentFactory, RefundFactory


pytestmark = pytest.mark.django_db(transaction=True)


def test_attempt_terminal_state_cannot_be_rewritten(payment):
    attempt = PaymentAttemptFactory(payment=payment, success=True)
    attempt.status = PaymentAttemptStatus.FAILED
    attempt.failure_reason = "rewritten terminal result"

    with pytest.raises(PaymentAttemptInvalidTransitionError):
        PaymentAttemptRepository.save_failure(attempt)

    assert PaymentAttemptRepository.get(attempt.pk).status == PaymentAttemptStatus.SUCCESS


def test_attempt_gateway_identity_cannot_be_overwritten(payment):
    attempt = PaymentAttemptFactory(payment=payment, success=True)
    original = attempt.gateway_reference
    attempt.gateway_reference = "conflicting-reference"

    with pytest.raises(PaymentAttemptIdentityConflictError):
        PaymentAttemptRepository.save_gateway_identity(attempt)

    assert PaymentAttemptRepository.get(attempt.pk).gateway_reference == original


def test_attempt_cas_rejects_a_racing_lifecycle_write(payment, monkeypatch):
    attempt = PaymentAttemptFactory(payment=payment)
    attempt.mark_failed(reason="our attempted result")
    original_clean = attempt.clean

    def concurrent_write_then_validate():
        PaymentAttemptRepository.model.objects.filter(pk=attempt.pk)._repository_update(
            _PAYMENT_CORE_REPOSITORY_WRITE_TOKEN,
            status=PaymentAttemptStatus.TIMEOUT,
            finished_at=timezone.now(),
            failure_reason="concurrent result",
            latency_ms=10,
        )
        original_clean()

    monkeypatch.setattr(attempt, "clean", concurrent_write_then_validate)
    with pytest.raises(PaymentConcurrencyError):
        PaymentAttemptRepository.save_failure(attempt)

    persisted = PaymentAttemptRepository.get(attempt.pk)
    assert persisted.status == PaymentAttemptStatus.TIMEOUT
    assert persisted.failure_reason == "concurrent result"


def test_refund_terminal_state_cannot_be_rewritten():
    payment = PaymentFactory(success=True, consumed=True)
    refund = RefundFactory(payment=payment, success=True)
    refund.status = RefundStatus.FAILED
    refund.failure_reason = "rewritten terminal result"

    with pytest.raises(PaymentInvalidTransitionError):
        RefundRepository.save_failure(refund)

    assert RefundRepository.get(refund.pk).status == RefundStatus.SUCCESS


def test_refund_gateway_identity_cannot_be_overwritten():
    payment = PaymentFactory(success=True, consumed=True)
    refund = RefundFactory(payment=payment, success=True)
    original = refund.gateway_reference
    refund.gateway_reference = "conflicting-refund-reference"

    with pytest.raises(PaymentGatewayIdentityConflictError):
        RefundRepository.save_success(refund)

    assert RefundRepository.get(refund.pk).gateway_reference == original


def test_refund_cas_rejects_a_racing_lifecycle_write(monkeypatch):
    payment = PaymentFactory(success=True, consumed=True)
    refund = RefundFactory(payment=payment)
    refund.mark_failed(reason="our attempted result")
    original_clean = refund.clean

    def concurrent_write_then_validate():
        RefundRepository.model.objects.filter(pk=refund.pk)._repository_update(
            _PAYMENT_CORE_REPOSITORY_WRITE_TOKEN,
            status=RefundStatus.SUCCESS,
            finished_at=timezone.now(),
            failure_reason="",
            gateway_reference="CONCURRENT-REF",
        )
        original_clean()

    monkeypatch.setattr(refund, "clean", concurrent_write_then_validate)
    with pytest.raises(PaymentConcurrencyError):
        RefundRepository.save_failure(refund)

    persisted = RefundRepository.get(refund.pk)
    assert persisted.status == RefundStatus.SUCCESS
    assert persisted.gateway_reference == "CONCURRENT-REF"


def test_mark_consumed_requires_success_unconsumed_and_current_version():
    pending = PaymentFactory(status=PaymentStatusType.PENDING, version=3)
    assert PaymentRepository.mark_consumed_if_current(
        payment_id=pending.pk, expected_version=3
    ) is False
    pending.refresh_from_db()
    assert pending.is_consumed is False

    successful = PaymentFactory(success=True, consumed=False, version=4)
    assert PaymentRepository.mark_consumed_if_current(
        payment_id=successful.pk, expected_version=3
    ) is False
    assert PaymentRepository.mark_consumed_if_current(
        payment_id=successful.pk, expected_version=4
    ) is True
    successful.refresh_from_db()
    assert successful.is_consumed is True
    assert successful.version == 5
    assert PaymentRepository.mark_consumed_if_current(
        payment_id=successful.pk, expected_version=5
    ) is False


def test_model_cancellation_delegates_to_state_machine(monkeypatch):
    order = OrderFactory()
    calls = {}

    def transition(*, order, to_status, **kwargs):
        calls["order_id"] = order.pk
        calls["to_status"] = to_status
        return order

    monkeypatch.setattr(OrderStateMachine, "transition", transition)
    assert order.mark_cancelled().pk == order.pk
    assert calls == {"order_id": order.pk, "to_status": OrderStatusType.cancelled}


def test_paid_order_cannot_be_cancelled_through_model_method():
    order = OrderFactory(paid=True)

    with pytest.raises(ValidationError):
        order.mark_cancelled()

    order.refresh_from_db()
    assert order.status == OrderStatusType.paid
    assert order.cancelled_date is None


def test_pending_order_can_be_cancelled_through_model_method():
    order = OrderFactory()
    InventoryService.reserve(order)

    cancelled = order.mark_cancelled()
    cancelled.refresh_from_db()
    assert cancelled.status == OrderStatusType.cancelled
    assert cancelled.cancelled_date is not None


def test_payment_core_queryset_writes_require_repository(payment):
    with pytest.raises(ValidationError):
        PaymentRepository.model.objects.filter(pk=payment.pk).update(
            status=PaymentStatusType.FAILED,
        )

    payment_copy = PaymentRepository.get(payment.pk)
    payment_copy.status = PaymentStatusType.FAILED
    with pytest.raises(ValidationError):
        payment_copy.save(update_fields=("status",))


def test_payment_attempt_queryset_and_instance_writes_require_repository(payment):
    attempt = PaymentAttemptFactory(payment=payment)

    with pytest.raises(ValidationError):
        PaymentAttemptRepository.model.objects.filter(pk=attempt.pk).update(
            status=PaymentAttemptStatus.FAILED,
        )

    attempt.status = PaymentAttemptStatus.FAILED
    with pytest.raises(ValidationError):
        attempt.save(update_fields=("status",))


def test_refund_queryset_and_instance_writes_require_repository():
    payment = PaymentFactory(success=True, consumed=True)
    refund = RefundFactory(payment=payment)

    with pytest.raises(ValidationError):
        RefundRepository.model.objects.filter(pk=refund.pk).update(
            status=RefundStatus.FAILED,
        )

    refund.status = RefundStatus.FAILED
    with pytest.raises(ValidationError):
        refund.save(update_fields=("status",))


def test_payment_core_bulk_writes_are_rejected(payment):
    payment_copy = PaymentRepository.get(payment.pk)
    payment_copy.status = PaymentStatusType.FAILED

    with pytest.raises(ValidationError):
        PaymentRepository.model.objects.bulk_update(
            [payment_copy],
            fields=("status",),
        )

    with pytest.raises(ValidationError):
        PaymentRepository.model.objects.bulk_create([])

    attempt = PaymentAttemptFactory(payment=payment)
    with pytest.raises(ValidationError):
        PaymentAttemptRepository.model.objects.bulk_update(
            [attempt],
            fields=("status",),
        )
    with pytest.raises(ValidationError):
        PaymentAttemptRepository.model.objects.bulk_create([])

    refund = RefundFactory(payment=PaymentFactory(success=True, consumed=True))
    with pytest.raises(ValidationError):
        RefundRepository.model.objects.bulk_update(
            [refund],
            fields=("status",),
        )
    with pytest.raises(ValidationError):
        RefundRepository.model.objects.bulk_create([])

    with pytest.raises(ValidationError):
        PaymentRepository.model._base_manager.filter(pk=payment.pk).update(
            status=PaymentStatusType.FAILED,
        )
    with pytest.raises(ValidationError):
        PaymentAttemptRepository.model._base_manager.filter(pk=attempt.pk).update(
            status=PaymentAttemptStatus.FAILED,
        )
    with pytest.raises(ValidationError):
        RefundRepository.model._base_manager.filter(pk=refund.pk).update(
            status=RefundStatus.FAILED,
        )


def test_force_update_cannot_reclassify_persisted_financial_records(payment):
    payment_copy = PaymentRepository.get(payment.pk)
    payment_copy._state.adding = True
    with pytest.raises(ValidationError):
        payment_copy.save(force_update=True)

    attempt = PaymentAttemptFactory(payment=payment)
    attempt._state.adding = True
    with pytest.raises(ValidationError):
        attempt.save(force_update=True)

    refund = RefundFactory(
        payment=PaymentFactory(success=True, consumed=True),
    )
    refund._state.adding = True
    with pytest.raises(ValidationError):
        refund.save(force_update=True)


def test_attempt_retry_fk_queryset_update_is_rejected_outside_delete_collector(
    payment,
):
    attempt = PaymentAttemptFactory(payment=payment)

    with pytest.raises(ValidationError):
        PaymentAttemptRepository.model.objects.filter(pk=attempt.pk).update(
            retry_of=None,
        )