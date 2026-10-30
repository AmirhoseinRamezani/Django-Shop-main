# order/services/coupon.py
from __future__ import annotations

import logging

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.translation import gettext as _

from order.events.order_event import OrderEventType
from order.models import (
    CouponModel,
    CouponReservation,
    CouponReservationReconciliation,
    CouponReservationStatus,
    CouponReconciliationOperation,
    CouponReconciliationStatus,
    OrderModel,
    OrderStatusType,
)

logger = logging.getLogger(__name__)

class CouponService:
    """Own coupon capacity, reservation lifecycle, and recovery evidence."""

    @staticmethod
    def get_valid_coupon(code: str) -> CouponModel:
        try:
            coupon = CouponModel.objects.get(code__iexact=code.strip())
        except CouponModel.DoesNotExist:
            raise ValidationError(_("Discount code is not valid"))

        if not coupon.is_valid():
            raise ValidationError(_("The discount code is expired or inactive"))
        return coupon

    @staticmethod
    @transaction.atomic
    def reserve_for_order(order: OrderModel) -> CouponReservation | None:
        """Reserve one capacity slot, idempotently, in the checkout transaction."""
        locked_order = OrderModel.objects.select_for_update().get(pk=order.pk)
        if not locked_order.coupon_id:
            return None

        existing = CouponReservation.objects.filter(order_id=locked_order.pk).first()
        if existing:
            if existing.coupon_id != locked_order.coupon_id:
                raise ValidationError(_("Order already has a different coupon reservation."))
            if existing.status != CouponReservationStatus.RESERVED:
                raise ValidationError(_("Coupon reservation is already terminal."))
            return existing

        coupon = CouponModel.objects.select_for_update().get(pk=locked_order.coupon_id)
        now = timezone.now()
        if (
            not coupon.is_active
            or (coupon.expiration_date and coupon.expiration_date <= now)
            or coupon.used_count + coupon.reserved_count >= coupon.max_limit_usage
        ):
            raise ValidationError(_("The discount code is no longer available."))
        if (
            locked_order.coupon_code != coupon.code
            or locked_order.coupon_discount_percent != coupon.discount_percent
        ):
            raise ValidationError(_("Coupon terms changed during checkout; please retry."))

        updated = CouponModel.objects.filter(
            pk=coupon.pk,
            is_active=True,
            used_count__lt=F("max_limit_usage") - F("reserved_count"),
        ).filter(
            models_expiration_filter(now)
        ).update(reserved_count=F("reserved_count") + 1)
        if updated != 1:
            raise ValidationError(_("The discount code is no longer available."))

        reservation = CouponReservation.objects.create(
            order=locked_order,
            coupon=coupon,
            status=CouponReservationStatus.RESERVED,
        )
        CouponReservationReconciliation.objects.create(
            order=locked_order,
            coupon=coupon,
            reservation=reservation,
            expected_operation=CouponReconciliationOperation.NONE,
            status=CouponReconciliationStatus.RESOLVED,
        )
        return reservation

    @staticmethod
    def has_unresolved_payment_outcome(order: OrderModel) -> bool:
        """Lock and inspect provider state using Order -> Payment -> Attempt order."""
        from payment.enums import PaymentAttemptStatus, PaymentStatusType
        from payment.models import PaymentResolution, PaymentResolutionStatus

        # Verification Phase C locks Payment and Attempt but does not lock Order.
        # Taking these locks while Order is held makes expiry/cancellation
        # serialize with a provider result already being persisted. Pending
        # Payments are always unresolved, so an in-flight gateway call cannot
        # lose its reservation merely because the expiry worker ran first.
        payments = list(
            order.payments.select_for_update().order_by("pk")
        )
        attempts_by_payment = {}
        for payment in payments:
            attempts_by_payment[payment.pk] = list(
                payment.attempts.select_for_update().order_by("attempt_number", "pk")
            )
        if PaymentResolution.objects.filter(
            payment__order_id=order.pk,
            status=PaymentResolutionStatus.OPEN,
        ).exists():
            return True

        paid_events = list(
            order.events.filter(type=OrderEventType.PAID).order_by("id")
        )
        payments_by_id = {payment.pk: payment for payment in payments}
        valid_paid_payment_ids = set()
        for event in paid_events:
            payment_id = event.payload.get("payment_id")
            attempt_id = event.payload.get("attempt_id")
            payment = payments_by_id.get(payment_id)
            if (
                payment
                and payment.status == PaymentStatusType.SUCCESS
                and payment.is_consumed
                and attempt_id
                and any(
                    attempt.pk == attempt_id
                    and attempt.status == PaymentAttemptStatus.SUCCESS
                    for attempt in attempts_by_payment[payment.pk]
                )
            ):
                valid_paid_payment_ids.add(payment.pk)

        # A successful/consumed Payment without matching canonical PAID event
        # evidence is an inconsistency, not permission to release capacity.
        if any(
            payment.status == PaymentStatusType.SUCCESS
            and payment.is_consumed
            and payment.pk not in valid_paid_payment_ids
            for payment in payments
        ):
            return True
        if paid_events and any(
            event.payload.get("payment_id") not in valid_paid_payment_ids
            for event in paid_events
        ):
            return True

        for payment in payments:
            if payment.status == PaymentStatusType.PENDING:
                return True
            if payment.status == PaymentStatusType.SUCCESS and not payment.is_consumed:
                return True
            if any(
                attempt.status in (PaymentAttemptStatus.PENDING, PaymentAttemptStatus.TIMEOUT)
                for attempt in attempts_by_payment[payment.pk]
            ):
                return True
        return False

    @staticmethod
    def schedule_reconciliation(order_id: int) -> None:
        """Schedule best-effort work after commit; the DB record is the outbox."""
        try:
            transaction.on_commit(
                lambda: CouponService.reconcile_order(order_id),
                robust=True,
            )
        except Exception:
            # The committed PAID/CANCELLED event and reservation are sufficient
            # for the periodic reconciliation command to recover if callback
            # registration itself fails. Never abort financial finalization.
            logger.exception(
                "Could not schedule coupon reconciliation for order_id=%s",
                order_id,
            )

    @classmethod
    def reconcile_order(cls, order_id: int) -> bool:
        """Infer a safe terminal operation from committed Order/payment evidence."""
        try:
            return cls._reconcile_order_transaction(order_id)
        except Exception as exc:
            # The reservation and reconciliation row were created at checkout.
            # This update is outside the failed accounting transaction, so the
            # verified payment's transaction can never be rolled back here.
            try:
                with transaction.atomic():
                    order = OrderModel.objects.select_for_update().get(pk=order_id)
                    paid_event = order.events.filter(
                        type=OrderEventType.PAID,
                    ).order_by("-id").first()
                    release_is_safe = (
                        order.status == OrderStatusType.cancelled
                        and paid_event is None
                        and not CouponService.has_unresolved_payment_outcome(order)
                    )
                    record = CouponReservationReconciliation.objects.select_for_update().filter(
                        order_id=order.pk,
                    ).first()
                    if record:
                        update_fields = [
                            "status", "failure_reason", "retry_count",
                            "last_attempt_at", "updated_at",
                        ]
                        if paid_event:
                            record.expected_operation = CouponReconciliationOperation.CONSUME
                            record.payment_id = paid_event.payload.get("payment_id") or None
                            record.attempt_id = paid_event.payload.get("attempt_id") or None
                            update_fields.extend(("expected_operation", "payment", "attempt"))
                        elif release_is_safe:
                            record.expected_operation = CouponReconciliationOperation.RELEASE
                            update_fields.append("expected_operation")
                        record.status = CouponReconciliationStatus.RETRY
                        record.failure_reason = f"{type(exc).__name__}: {exc}"[:4000]
                        record.retry_count = F("retry_count") + 1
                        record.last_attempt_at = timezone.now()
                        record.save(update_fields=tuple(update_fields))
            except Exception:
                logger.exception(
                    "Could not persist coupon reconciliation failure for order_id=%s",
                    order_id,
                )
            logger.exception("Coupon reconciliation failed for order_id=%s", order_id)
            return False

    @staticmethod
    @transaction.atomic
    def _reconcile_order_transaction(order_id: int) -> bool:
        from payment.enums import PaymentAttemptStatus, PaymentStatusType
        from payment.models import (
            PaymentAttempt,
            PaymentModel,
            PaymentResolution,
            PaymentResolutionStatus,
        )

        order = OrderModel.objects.select_for_update().get(pk=order_id)
        # The Order lock serializes all supported lifecycle writers. Read the
        # recovery row first without locking it; financial rows are locked
        # before any coupon/reservation rows below.
        record_ref = CouponReservationReconciliation.objects.filter(
            order_id=order.pk,
        ).first()
        if record_ref is None:
            logger.error("Missing coupon reconciliation record for order_id=%s", order_id)
            return False

        operation = None
        payment = None
        attempt = None
        paid_event = order.events.filter(type=OrderEventType.PAID).order_by("-id").first()
        if paid_event:
            # The canonical PAID event survives later processing/cancellation
            # transitions. Its matching consumed Payment is still the source of
            # truth for coupon consumption.
            payment_id = paid_event.payload.get("payment_id")
            attempt_id = paid_event.payload.get("attempt_id")
            if payment_id and attempt_id:
                payment = PaymentModel.objects.select_for_update().filter(
                    pk=payment_id,
                    order_id=order.pk,
                    status=PaymentStatusType.SUCCESS,
                    is_consumed=True,
                ).first()
                if payment:
                    attempt = PaymentAttempt.objects.select_for_update().filter(
                        pk=attempt_id,
                        payment_id=payment.pk,
                        status=PaymentAttemptStatus.SUCCESS,
                    ).first()
                if payment and attempt:
                    operation = CouponReconciliationOperation.CONSUME

        unresolved_outcome = False
        if operation is None and paid_event is None and (
            order.status == OrderStatusType.cancelled
            or (order.status == OrderStatusType.pending and order.is_expired())
        ):
            unresolved_outcome = CouponService.has_unresolved_payment_outcome(order)
            if order.status == OrderStatusType.cancelled and not unresolved_outcome:
                operation = CouponReconciliationOperation.RELEASE

        if operation is None:
            if order.is_paid or (
                order.status == OrderStatusType.cancelled
                and (paid_event is not None or unresolved_outcome)
            ) or (
                order.status == OrderStatusType.pending
                and order.is_expired()
                and unresolved_outcome
            ):
                inconsistent_payment = None
                inconsistent_attempt = None
                if order.is_paid and paid_event is None:
                    candidates = list(order.payments.select_for_update().order_by("pk"))
                    inconsistent_payment = next(
                        (p for p in candidates if p.status == PaymentStatusType.SUCCESS),
                        None,
                    )
                    if inconsistent_payment is not None:
                        attempts = list(
                            inconsistent_payment.attempts.select_for_update().order_by("-attempt_number", "-pk")
                        )
                        inconsistent_attempt = attempts[0] if attempts else None

                record = CouponReservationReconciliation.objects.select_for_update().get(
                    pk=record_ref.pk,
                )
                update_fields = [
                    "status", "failure_reason", "retry_count",
                    "last_attempt_at", "updated_at",
                ]
                if paid_event is not None:
                    record.expected_operation = CouponReconciliationOperation.CONSUME
                    record.payment_id = paid_event.payload.get("payment_id") or None
                    record.attempt_id = paid_event.payload.get("attempt_id") or None
                    update_fields.extend(("expected_operation", "payment", "attempt"))
                elif inconsistent_payment is not None:
                    record.payment = inconsistent_payment
                    record.attempt = inconsistent_attempt
                    record.expected_operation = CouponReconciliationOperation.CONSUME
                    update_fields.extend(("expected_operation", "payment", "attempt"))
                elif unresolved_outcome:
                    # Link the recovery record to the provider execution that
                    # is preventing release. The same Attempt row will reflect
                    # a later SUCCESS/TIMEOUT transition.
                    unresolved_payments = list(
                        order.payments.select_for_update().order_by("pk")
                    )
                    candidate_requires_review = any(
                        p.status == PaymentStatusType.SUCCESS and not p.is_consumed
                        for p in unresolved_payments
                    )
                    candidate = next(
                        (p for p in unresolved_payments if p.status == PaymentStatusType.SUCCESS and not p.is_consumed),
                        None,
                    ) or next(
                        (p for p in unresolved_payments if p.status == PaymentStatusType.PENDING),
                        None,
                    )
                    candidate_attempt = None
                    if candidate is not None:
                        unresolved_attempts = list(
                            candidate.attempts.select_for_update().order_by("-attempt_number", "-pk")
                        )
                        candidate_attempt = unresolved_attempts[0] if unresolved_attempts else None
                    else:
                        for possible_payment in unresolved_payments:
                            possible_attempt = possible_payment.attempts.select_for_update().filter(
                                status__in=(PaymentAttemptStatus.PENDING, PaymentAttemptStatus.TIMEOUT),
                            ).order_by("-attempt_number", "-pk").first()
                            if possible_attempt is not None:
                                candidate = possible_payment
                                candidate_attempt = possible_attempt
                                break
                        if candidate is None:
                            resolution = PaymentResolution.objects.filter(
                                payment__order_id=order.pk,
                                status=PaymentResolutionStatus.OPEN,
                            ).select_related("payment", "attempt").first()
                            if resolution is not None:
                                candidate = resolution.payment
                                candidate_attempt = resolution.attempt
                                candidate_requires_review = True
                    if candidate is not None:
                        record.payment = candidate
                        record.attempt = candidate_attempt
                        record.expected_operation = (
                            CouponReconciliationOperation.REVIEW
                            if candidate_requires_review
                            else CouponReconciliationOperation.NONE
                        )
                        update_fields.extend(("payment", "attempt", "expected_operation"))
                record.status = CouponReconciliationStatus.RETRY
                record.failure_reason = (
                    "Authoritative payment evidence is inconsistent; coupon capacity "
                    "is retained for manual reconciliation."
                    if order.is_paid or paid_event is not None
                    else "Provider outcome remains unresolved; coupon capacity is retained."
                )
                record.retry_count = F("retry_count") + 1
                record.last_attempt_at = timezone.now()
                record.save(update_fields=tuple(update_fields))
            return False

        if operation == CouponReconciliationOperation.RELEASE:
            # A previous cancellation may have retained stock because the
            # gateway outcome was unknown. Restore it now only after the
            # payment path is definitively ineligible. Keep Product locks
            # before Coupon locks, matching checkout's lock order.
            from order.services.inventory import InventoryService
            InventoryService.restore(order)

        coupon = CouponModel.objects.select_for_update().get(pk=record_ref.coupon_id)
        reservation = None
        if record_ref.reservation_id:
            reservation = CouponReservation.objects.select_for_update().filter(
                pk=record_ref.reservation_id,
            ).first()
        record = CouponReservationReconciliation.objects.select_for_update().get(
            pk=record_ref.pk,
        )
        
        if reservation is None:
            raise ValidationError(
                _("Coupon reconciliation has no durable reservation.")
            )

        # A terminal reservation is the idempotency boundary. Never adjust
        # counters a second time when a worker or callback is retried.
        if reservation.status == CouponReservationStatus.CONSUMED:
            if operation != CouponReconciliationOperation.CONSUME:
                raise ValidationError(
                    _("Consumed coupon reservation conflicts with inferred operation.")
                )
            record.expected_operation = CouponReconciliationOperation.CONSUME
            record.payment = payment
            record.attempt = attempt
            record.status = CouponReconciliationStatus.RESOLVED
            record.failure_reason = ""
            record.resolved_at = record.resolved_at or timezone.now()
            record.last_attempt_at = timezone.now()
            record.save(update_fields=(
                "expected_operation", "payment", "attempt", "status",
                "failure_reason", "resolved_at", "last_attempt_at", "updated_at",
            ))
            return True

        if reservation.status == CouponReservationStatus.RELEASED:
            if operation != CouponReconciliationOperation.RELEASE:
                raise ValidationError(
                    _("Released coupon reservation conflicts with inferred operation.")
                )
            record.expected_operation = CouponReconciliationOperation.RELEASE
            record.status = CouponReconciliationStatus.RESOLVED
            record.failure_reason = ""
            record.resolved_at = record.resolved_at or timezone.now()
            record.last_attempt_at = timezone.now()
            record.save(update_fields=(
                "expected_operation", "status", "failure_reason",
                "resolved_at", "last_attempt_at", "updated_at",
            ))
            return True

        if reservation.status != CouponReservationStatus.RESERVED:
            raise ValidationError(_("Unsupported coupon reservation state."))

        # Keep the aggregate counter and reservation state in one transaction.
        # The conditional update prevents underflow and protects against
        # corrupted counters; a failure is recorded by reconcile_order() in
        # its separate recovery transaction.
        if operation == CouponReconciliationOperation.CONSUME:
            updated = CouponModel.objects.filter(
                pk=coupon.pk,
                reserved_count__gte=1,
            ).update(
                reserved_count=F("reserved_count") - 1,
                used_count=F("used_count") + 1,
            )
            if updated != 1:
                raise ValidationError(
                    _("Coupon reservation counter is inconsistent; manual reconciliation required.")
                )

            reservation.status = CouponReservationStatus.CONSUMED
            reservation.consumed_at = timezone.now()
            reservation.save(update_fields=("status", "consumed_at"))

        elif operation == CouponReconciliationOperation.RELEASE:
            updated = CouponModel.objects.filter(
                pk=coupon.pk,
                reserved_count__gte=1,
            ).update(
                reserved_count=F("reserved_count") - 1,
            )
            if updated != 1:
                raise ValidationError(
                    _("Coupon reservation counter is inconsistent; manual reconciliation required.")
                )

            reservation.status = CouponReservationStatus.RELEASED
            reservation.released_at = timezone.now()
            reservation.save(update_fields=("status", "released_at"))
        else:
            raise ValidationError(_("Unsupported coupon reconciliation operation."))

        record.expected_operation = operation
        if operation == CouponReconciliationOperation.CONSUME:
            record.payment = payment
            record.attempt = attempt
        record.status = CouponReconciliationStatus.RESOLVED
        record.failure_reason = ""
        record.resolved_at = timezone.now()
        record.last_attempt_at = timezone.now()
        record.save(update_fields=(
            "expected_operation", "payment", "attempt", "status",
            "failure_reason", "resolved_at", "last_attempt_at", "updated_at",
        ))
        return True

    @staticmethod
    @transaction.atomic
    def consume(coupon: CouponModel):
        """Legacy direct consumption; new Orders must use reservations."""
        updated = CouponModel.objects.filter(
            pk=coupon.pk,
            is_active=True,
            used_count__lt=F("max_limit_usage") - F("reserved_count"),
        ).filter(models_expiration_filter(timezone.now())).update(
            used_count=F("used_count") + 1,
        )
        if updated != 1:
            raise ValidationError(_("Coupon cannot be consumed"))

    @staticmethod
    @transaction.atomic
    def rollback(coupon: CouponModel):
        # Kept for the legacy refund policy. Reservation-backed consumed uses
        # are historical and must not be reversed into an available slot.
        has_consumed_reservation = CouponReservation.objects.filter(
            coupon_id=coupon.pk,
            status=CouponReservationStatus.CONSUMED,
        ).exists()
        if has_consumed_reservation:
            return
        CouponModel.objects.filter(
            pk=coupon.pk,
            used_count__gt=0,
        ).update(used_count=F("used_count") - 1)


def models_expiration_filter(now):
    from django.db.models import Q
    return Q(expiration_date__isnull=True) | Q(expiration_date__gt=now)
