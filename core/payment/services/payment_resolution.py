# payment/services/payment_resolution.py
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from order.models import OrderModel, OrderStatusType
from order.events.order_event import OrderEventType
from payment.enums import PaymentAttemptStatus
from payment.exceptions import PaymentInvariantViolation
from payment.models import (
    PaymentAttempt,
    PaymentResolution,
    PaymentResolutionReason,
    PaymentResolutionStatus,
)
from payment.repositories.payment_repository import PaymentRepository


class PaymentResolutionService:
    """Owns only durable inconsistency registration and explicit resolution."""

    @classmethod
    def register(
        cls,
        *,
        payment_id: int,
        reason: PaymentResolutionReason | None = None,
        attempt_id: int | None = None,
    ) -> PaymentResolution | None:
        if reason is not None and reason not in PaymentResolutionReason.values:
            raise ValidationError({"reason": "Unsupported payment resolution reason."})

        # Keep the cross-aggregate lock order consistent with finalization.
        payment_ref = PaymentRepository.get(payment_id)
        with transaction.atomic():
            order = OrderModel.objects.select_for_update().get(
                pk=payment_ref.order_id
            )
            payment = PaymentRepository.get_for_update(payment_id)
            if payment.order_id != order.pk:
                raise PaymentInvariantViolation(
                    "Payment/order identity changed during resolution registration."
                )
            if not payment.is_successful:
                raise PaymentInvariantViolation(
                    "Only successful Payments can have a Resolution."
                )

            attempt = None
            if attempt_id is not None:
                attempt = PaymentAttempt.objects.select_for_update().get(
                    pk=attempt_id
                )
                if attempt.payment_id != payment.pk:
                    raise PaymentInvariantViolation(
                        "PaymentAttempt does not belong to the expected Payment."
                    )
                if attempt.status != PaymentAttemptStatus.SUCCESS:
                    raise PaymentInvariantViolation(
                        "Resolution Attempt must be successful."
                    )

            existing = PaymentResolution.objects.filter(payment_id=payment.pk).first()
            if existing is not None:
                return existing
            if payment.is_consumed:
                if reason is None:
                    return None
                raise PaymentInvariantViolation("A consumed Payment cannot receive a new Resolution.")
            detected_reason = cls._reason_for_order(order)
            if detected_reason is None:
                return None
            if reason is not None and reason != detected_reason:
                raise PaymentInvariantViolation(
                    "Resolution reason does not match the authoritative Order state."
                )
            reason = detected_reason

            try:
                # Savepoint allows a uniqueness race to be recovered without
                # leaving the surrounding transaction marked for rollback.
                with transaction.atomic():
                    return PaymentResolution.objects.create(
                        payment=payment,
                        attempt=attempt,
                        reason=reason,
                        order_status_at_detection=str(order.status),
                    )
            except IntegrityError as exc:
                cause = exc.__cause__
                constraint_name = getattr(
                    getattr(cause, "diag", None), "constraint_name", ""
                )
                sqlstate = getattr(cause, "pgcode", None) or getattr(cause, "sqlstate", None)
                is_payment_unique_race = (
                    sqlstate == "23505"
                    and constraint_name.endswith("_payment_id_key")
                ) or (
                    "UNIQUE constraint failed: payment_paymentresolution.payment_id"
                    in str(cause)
                )
                if not is_payment_unique_race:
                    raise
                existing = PaymentResolution.objects.filter(payment_id=payment.pk).first()
                if existing is None:
                    raise
                return existing

    @staticmethod
    def _reason_for_order(order: OrderModel) -> PaymentResolutionReason | None:
        if order.status == OrderStatusType.cancelled:
            terminal_event = (
                order.events.filter(
                    type__in=(OrderEventType.EXPIRED, OrderEventType.CANCELLED)
                )
                .order_by("-id")
                .first()
            )
            if terminal_event and terminal_event.type == OrderEventType.EXPIRED:
                return PaymentResolutionReason.ORDER_EXPIRED
            return PaymentResolutionReason.ORDER_CANCELLED
        if order.status == OrderStatusType.pending and order.is_expired():
            return PaymentResolutionReason.ORDER_DEADLINE_PASSED
        if order.is_paid:
            return PaymentResolutionReason.ORDER_ALREADY_PAID
        if order.status == OrderStatusType.failed:
            return PaymentResolutionReason.FINALIZATION_INCONSISTENCY
        return None

    @classmethod
    def resolve(
        cls,
        *,
        resolution_id: int,
        actor=None,
        note: str = "",
    ) -> PaymentResolution:
        """Explicitly close an investigation; never changes financial/order state."""
        initial = PaymentResolution.objects.only("payment_id").get(pk=resolution_id)
        payment_ref = PaymentRepository.get(initial.payment_id)
        with transaction.atomic():
            order = OrderModel.objects.select_for_update().get(
                pk=payment_ref.order_id
            )
            payment = PaymentRepository.get_for_update(payment_ref.pk)
            resolution = PaymentResolution.objects.select_for_update().get(
                pk=resolution_id
            )
            if resolution.payment_id != payment.pk or order.pk != payment.order_id:
                raise PaymentInvariantViolation(
                    "Resolution ownership changed during resolution."
                )
            if resolution.status == PaymentResolutionStatus.RESOLVED:
                return resolution
            if not actor or not getattr(actor, "is_authenticated", False):
                raise ValidationError(
                    "An authenticated operator is required to resolve a record."
                )
            if not note or not note.strip():
                raise ValidationError(
                    "A resolution note is required for auditability."
                )
            resolution.status = PaymentResolutionStatus.RESOLVED
            resolution.resolved_at = timezone.now()
            resolution.resolved_by = actor
            resolution.resolution_note = note.strip()
            resolution.save(
                update_fields=(
                    "status",
                    "resolved_at",
                    "resolved_by",
                    "resolution_note",
                    "updated_at",
                )
            )
            return resolution

    @classmethod
    def resolve_after_verified_finalization(
        cls,
        *,
        payment_id: int,
        order_id: int,
    ) -> PaymentResolution | None:
        """Close an open record only when canonical consumption is verifiable."""
        with transaction.atomic():
            order = OrderModel.objects.select_for_update().get(pk=order_id)
            payment = PaymentRepository.get_for_update(payment_id)
            if (
                payment.order_id != order.pk
                or not payment.is_successful
                or not payment.is_consumed
            ):
                return None
            paid_event = order.events.filter(type=OrderEventType.PAID).order_by("-id").first()
            if paid_event is None or paid_event.payload.get("payment_id") != payment.pk:
                return None
            resolution = (
                PaymentResolution.objects.select_for_update()
                .filter(payment_id=payment.pk, status=PaymentResolutionStatus.OPEN)
                .first()
            )
            if resolution is None:
                return None
            resolution.status = PaymentResolutionStatus.RESOLVED
            resolution.resolved_at = timezone.now()
            resolution.resolved_by = None
            resolution.resolution_note = (
                "Automatically resolved after canonical order finalization was "
                "verified by the matching PAID event and consumed Payment."
            )
            resolution.save(
                update_fields=(
                    "status",
                    "resolved_at",
                    "resolved_by",
                    "resolution_note",
                    "updated_at",
                )
            )
            return resolution
