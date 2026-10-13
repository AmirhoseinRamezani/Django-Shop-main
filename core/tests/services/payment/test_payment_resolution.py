# tests/services/payment/test_payment_resolution.py
import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from payment.enums import PaymentStatusType
from payment.exceptions import PaymentInvariantViolation
from payment.models import (
    PaymentResolution,
    PaymentResolutionReason,
    PaymentResolutionStatus,
)
from payment.services.payment_resolution import PaymentResolutionService
from tests.factories.payment import PaymentAttemptFactory, PaymentFactory
from tests.factories.order import OrderFactory
from tests.factories.accounts import UserFactory

pytestmark = [pytest.mark.django_db, pytest.mark.service]


def _successful_unconsumed_payment():
    order = OrderFactory(cancelled=True)
    payment = PaymentFactory(order=order, status=PaymentStatusType.SUCCESS, is_consumed=False)
    attempt = PaymentAttemptFactory(payment=payment, success=True)
    return order, payment, attempt


def test_register_is_idempotent_and_preserves_first_reason():
    _, payment, attempt = _successful_unconsumed_payment()

    first = PaymentResolutionService.register(
        payment_id=payment.pk,
        attempt_id=attempt.pk,
        reason=PaymentResolutionReason.ORDER_CANCELLED,
    )
    duplicate = PaymentResolutionService.register(
        payment_id=payment.pk,
        reason=PaymentResolutionReason.ORDER_ALREADY_PAID,
    )

    assert duplicate.pk == first.pk
    assert duplicate.reason == PaymentResolutionReason.ORDER_CANCELLED
    assert duplicate.attempt_id == attempt.pk
    assert duplicate.status == PaymentResolutionStatus.OPEN
    payment.refresh_from_db()
    assert payment.status == PaymentStatusType.SUCCESS
    assert payment.is_consumed is False
    assert not payment.refunds.exists()


def test_register_rejects_attempt_from_another_payment():
    _, payment, _ = _successful_unconsumed_payment()
    _, other_payment, other_attempt = _successful_unconsumed_payment()

    with pytest.raises(PaymentInvariantViolation):
        PaymentResolutionService.register(
            payment_id=payment.pk,
            attempt_id=other_attempt.pk,
            reason=PaymentResolutionReason.FINALIZATION_INCONSISTENCY,
        )

    assert not PaymentResolution.objects.filter(payment=payment).exists()
    assert other_payment.status == PaymentStatusType.SUCCESS


def test_database_enforces_one_resolution_per_payment():
    _, payment, _ = _successful_unconsumed_payment()
    PaymentResolutionService.register(
        payment_id=payment.pk,
        reason=PaymentResolutionReason.ORDER_CANCELLED,
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        PaymentResolution.objects.create(
            payment=payment,
            reason=PaymentResolutionReason.ORDER_EXPIRED,
            order_status_at_detection="1",
        )


def test_explicit_resolution_requires_authenticated_actor_and_note():
    _, payment, _ = _successful_unconsumed_payment()
    resolution = PaymentResolutionService.register(
        payment_id=payment.pk,
        reason=PaymentResolutionReason.ORDER_CANCELLED,
    )

    with pytest.raises(ValidationError):
        PaymentResolutionService.resolve(resolution_id=resolution.pk, note="reviewed")

    actor = UserFactory()
    resolved = PaymentResolutionService.resolve(
        resolution_id=resolution.pk,
        actor=actor,
        note="Reviewed; follow-up handled by support.",
    )
    assert resolved.status == PaymentResolutionStatus.RESOLVED
    assert resolved.resolved_at is not None
    assert resolved.resolved_by_id == actor.pk
    assert resolved.resolution_note == "Reviewed; follow-up handled by support."


def test_resolved_resolution_cannot_be_reopened_by_duplicate_registration():
    _, payment, _ = _successful_unconsumed_payment()
    actor = UserFactory()
    resolution = PaymentResolutionService.register(
        payment_id=payment.pk,
        reason=PaymentResolutionReason.ORDER_CANCELLED,
    )
    PaymentResolutionService.resolve(
        resolution_id=resolution.pk,
        actor=actor,
        note="Reviewed and closed.",
    )

    duplicate = PaymentResolutionService.register(
        payment_id=payment.pk,
        reason=PaymentResolutionReason.ORDER_EXPIRED,
    )
    assert duplicate.status == PaymentResolutionStatus.RESOLVED
    assert duplicate.reason == PaymentResolutionReason.ORDER_CANCELLED


def test_successful_payment_for_cancelled_order_is_tracked_without_mutation():
    from order.models import OrderStatusType
    from payment.services.verify import synchronize_successful_payment

    order = OrderFactory(cancelled=True)
    payment = PaymentFactory(order=order, status=PaymentStatusType.SUCCESS, is_consumed=False)
    attempt = PaymentAttemptFactory(payment=payment, success=True)

    result = synchronize_successful_payment(payment_id=payment.pk)

    payment.refresh_from_db()
    order.refresh_from_db()
    resolution = PaymentResolution.objects.get(payment=payment)
    assert result.pk == payment.pk
    assert payment.status == PaymentStatusType.SUCCESS
    assert payment.is_consumed is False
    assert order.status == OrderStatusType.cancelled
    assert resolution.status == PaymentResolutionStatus.OPEN
    assert resolution.reason == PaymentResolutionReason.ORDER_CANCELLED
    assert resolution.attempt_id == attempt.pk
    assert not payment.refunds.exists()


def test_successful_payment_for_expired_pending_order_records_deadline_reason():
    from payment.services.verify import synchronize_successful_payment

    order = OrderFactory(expired=True)
    payment = PaymentFactory(order=order, status=PaymentStatusType.SUCCESS, is_consumed=False)
    PaymentAttemptFactory(payment=payment, success=True)

    synchronize_successful_payment(payment_id=payment.pk)

    resolution = PaymentResolution.objects.get(payment=payment)
    assert resolution.reason == PaymentResolutionReason.ORDER_DEADLINE_PASSED
    assert resolution.status == PaymentResolutionStatus.OPEN
    payment.refresh_from_db()
    assert payment.status == PaymentStatusType.SUCCESS
    assert payment.is_consumed is False


def test_successful_payment_does_not_finalize_order_already_paid_by_another_payment():
    from order.models import OrderStatusType
    from order.services.state_machine import OrderStateMachine
    from payment.services.verify import synchronize_successful_payment

    order = OrderFactory(paid=True)
    payment = PaymentFactory(order=order, status=PaymentStatusType.SUCCESS, is_consumed=False)
    PaymentAttemptFactory(payment=payment, success=True)

    synchronize_successful_payment(payment_id=payment.pk)

    resolution = PaymentResolution.objects.get(payment=payment)
    assert resolution.reason == PaymentResolutionReason.ORDER_ALREADY_PAID
    assert resolution.status == PaymentResolutionStatus.OPEN
    payment.refresh_from_db()
    order.refresh_from_db()
    assert payment.status == PaymentStatusType.SUCCESS
    assert payment.is_consumed is False
    assert order.status == OrderStatusType.paid


def test_resolution_closes_only_after_verified_canonical_finalization():
    from order.models import OrderStatusType
    from order.services.state_machine import OrderStateMachine
    from payment.services.verify import synchronize_successful_payment

    order = OrderFactory(failed=True)
    payment = PaymentFactory(order=order, status=PaymentStatusType.SUCCESS, is_consumed=False)
    PaymentAttemptFactory(payment=payment, success=True)

    synchronize_successful_payment(payment_id=payment.pk)
    resolution = PaymentResolution.objects.get(payment=payment)
    assert resolution.status == PaymentResolutionStatus.OPEN
    assert resolution.reason == PaymentResolutionReason.FINALIZATION_INCONSISTENCY

    OrderStateMachine.transition(order=order, to_status=OrderStatusType.pending)
    synchronize_successful_payment(payment_id=payment.pk)

    resolution.refresh_from_db()
    payment.refresh_from_db()
    assert payment.is_consumed is True
    assert resolution.status == PaymentResolutionStatus.RESOLVED
    assert resolution.resolved_at is not None
    assert "canonical order finalization was verified" in resolution.resolution_note


def test_unexpected_finalization_error_propagates_without_creating_resolution(monkeypatch):
    from payment.services.verify import synchronize_successful_payment

    order, payment, _ = _successful_unconsumed_payment()

    def explode(**kwargs):
        raise RuntimeError("unexpected programming failure")

    monkeypatch.setattr("payment.services.verify.confirm_order_payment", explode)
    with pytest.raises(RuntimeError, match="unexpected programming failure"):
        synchronize_successful_payment(payment_id=payment.pk)

    payment.refresh_from_db()
    order.refresh_from_db()
    assert payment.status == PaymentStatusType.SUCCESS
    assert payment.is_consumed is False
    assert not PaymentResolution.objects.filter(payment=payment).exists()


def test_duplicate_after_canonical_consumption_does_not_create_resolution_if_order_later_changes():
    from order.events.order_event import OrderEvent, OrderEventType
    from order.models import OrderStatusType
    from order.services.state_machine import OrderStateMachine
    from payment.services.verify import synchronize_successful_payment

    order = OrderFactory(paid=True)
    payment = PaymentFactory(order=order, status=PaymentStatusType.SUCCESS, is_consumed=True)
    PaymentAttemptFactory(payment=payment, success=True)
    OrderEvent.objects.create(
        order=order,
        type=OrderEventType.PAID,
        payload={"payment_id": payment.pk},
    )
    # Simulate a legitimate later lifecycle transition without replaying payment.
    OrderStateMachine.transition(order=order, to_status=OrderStatusType.processing)
    OrderStateMachine.transition(order=order, to_status=OrderStatusType.cancelled)

    result = synchronize_successful_payment(payment_id=payment.pk)

    assert result.pk == payment.pk
    assert not PaymentResolution.objects.filter(payment=payment).exists()


def test_financial_validation_error_is_not_converted_to_resolution(monkeypatch):
    """Only typed Order lifecycle conflicts are eligible for resolution."""
    from django.core.exceptions import ValidationError as DjangoValidationError
    from payment.services.verify import synchronize_successful_payment

    order = OrderFactory()
    payment = PaymentFactory(
        order=order,
        status=PaymentStatusType.SUCCESS,
        is_consumed=False,
    )
    PaymentAttemptFactory(payment=payment, success=True)

    def financial_mismatch(**kwargs):
        raise DjangoValidationError("Payment amount does not match Order snapshot")

    monkeypatch.setattr("payment.services.verify.confirm_order_payment", financial_mismatch)
    with pytest.raises(DjangoValidationError, match="amount does not match"):
        synchronize_successful_payment(payment_id=payment.pk)

    payment.refresh_from_db()
    assert payment.status == PaymentStatusType.SUCCESS
    assert payment.is_consumed is False
    assert not PaymentResolution.objects.filter(payment=payment).exists()


def test_unrecognized_validation_error_is_not_converted_to_resolution(monkeypatch):
    from django.core.exceptions import ValidationError as DjangoValidationError
    from payment.services.verify import synchronize_successful_payment

    order = OrderFactory()
    payment = PaymentFactory(order=order, status=PaymentStatusType.SUCCESS, is_consumed=False)
    PaymentAttemptFactory(payment=payment, success=True)

    def unexpected_validation(**kwargs):
        raise DjangoValidationError("Missing successful attempt")

    monkeypatch.setattr("payment.services.verify.confirm_order_payment", unexpected_validation)
    with pytest.raises(DjangoValidationError, match="Missing successful attempt"):
        synchronize_successful_payment(payment_id=payment.pk)
    assert not PaymentResolution.objects.filter(payment=payment).exists()


def test_admin_resolution_action_form_requires_real_operator_note():
    from payment.admin import PaymentResolutionActionForm

    empty = PaymentResolutionActionForm(data={"action": "mark_resolved", "select_across": "0"})
    valid = PaymentResolutionActionForm(
        data={
            "action": "mark_resolved",
            "select_across": "0",
            "resolution_note": "Compared provider inquiry with the successful attempt; case documented.",
        }
    )
    # Django Admin populates ActionForm.action choices from ModelAdmin actions
    # at request time. A standalone form instance has no action choices yet.
    for form in (empty, valid):
        form.fields["action"].choices = [
            ("mark_resolved", "Resolve selected payment investigations")
        ]

    assert not empty.is_valid()
    assert valid.is_valid()
    assert valid.cleaned_data["resolution_note"].startswith("Compared provider inquiry")


def test_cancelled_order_with_missing_successful_attempt_is_not_resolution(monkeypatch):
    from django.core.exceptions import ValidationError as DjangoValidationError
    from payment.services.verify import synchronize_successful_payment

    order = OrderFactory(cancelled=True)
    payment = PaymentFactory(order=order, status=PaymentStatusType.SUCCESS, is_consumed=False)
    # Deliberately no successful PaymentAttempt: this is missing financial
    # evidence, not a recognized Order-only conflict.
    with pytest.raises(DjangoValidationError, match="No successful payment attempt"):
        synchronize_successful_payment(payment_id=payment.pk)

    assert not PaymentResolution.objects.filter(payment=payment).exists()
    payment.refresh_from_db()
    assert payment.status == PaymentStatusType.SUCCESS
    assert payment.is_consumed is False
