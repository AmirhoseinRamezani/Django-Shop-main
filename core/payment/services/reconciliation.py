# core/payment/services/reconciliation.py
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.db import transaction

from payment.enums import PaymentAttemptStatus
from payment.exceptions import PaymentGatewayError, PaymentInvariantViolation
from payment.models import PaymentAttempt, PaymentModel
from payment.providers.base import GatewayInquiryResult
from payment.repositories.payment_attempt_repository import (
    PaymentAttemptRepository,
)
from payment.repositories.payment_repository import PaymentRepository
from order.services.confirm_payment import confirm_order_payment
from payment.services.gateway_service import GatewayService


@dataclass(frozen=True, slots=True)
class ReconciliationSnapshot:
    payment_id: int
    order_id: int
    attempt_id: int
    attempt_number: int
    authority_id: str
    amount: Decimal
    currency: str
    gateway: Any


class PaymentReconciliationService:
    """
    Reconcile an unresolved PaymentAttempt without executing the payment again.

    Reconciliation is evidence retrieval, not a retry path:

        DB snapshot -> gateway inquiry -> DB reconciliation

    Unknown inquiry outcomes remain PENDING.  Only a provider inquiry that
    positively establishes a successful transaction may move the Payment and
    its authoritative Attempt to SUCCESS.

    External gateway I/O is never performed while database locks are held.
    """

    @classmethod
    def reconcile_payment(
        cls,
        *,
        payment_id: int,
        attempt_id: int | None = None,
    ) -> PaymentModel:
        snapshot = cls._build_snapshot(
            payment_id=payment_id,
            attempt_id=attempt_id,
        )

        try:
            result = GatewayService.inquire(
                authority=snapshot.authority_id,
                order_id=str(snapshot.order_id),
                amount=snapshot.amount,
                currency=snapshot.currency,
                gateway=snapshot.gateway,
            )
        except PaymentGatewayError:
            # Transport/capability/unknown provider outcomes never change the
            # local financial state. The caller can retry reconciliation later.
            raise

        cls._validate_inquiry_result(
            result=result,
            snapshot=snapshot,
        )

        if not result.success:
            # A negative inquiry result is deliberately not interpreted as a
            # definitive payment failure because the normalized inquiry DTO has
            # no terminal failure state. The Payment remains PENDING.
            return PaymentRepository.get(payment_id)

        with transaction.atomic():
            payment = PaymentRepository.get_for_update(payment_id)
            attempt = PaymentAttemptRepository.get_for_update(
                snapshot.attempt_id,
            )

            cls._validate_reconciliation_target(
                payment=payment,
                attempt=attempt,
                snapshot=snapshot,
            )

            gateway_reference = cls._normalize(
                result.gateway_reference,
            )
            if not gateway_reference:
                raise PaymentInvariantViolation(
                    "Successful payment inquiry requires a gateway reference."
                )

            gateway_transaction_id = cls._normalize(
                result.gateway_transaction_id,
            )

            attempt.mark_success(
                authority_id=snapshot.authority_id,
                gateway_reference=gateway_reference,
                gateway_transaction_id=gateway_transaction_id,
                response_code=result.response_code or "",
                gateway_message=result.message or "",
            )
            PaymentAttemptRepository.save_success(attempt)

            payment.succeed()
            PaymentRepository.save(
                payment,
                update_fields=("status",),
            )

        # Reuse the canonical Order -> Payment consumption workflow. This keeps
        # reconciliation from introducing a second implementation of order-side
        # financial effects.
        confirm_order_payment(order_id=snapshot.order_id)
        return PaymentRepository.get(payment_id)

    @classmethod
    def _build_snapshot(
        cls,
        *,
        payment_id: int,
        attempt_id: int | None,
    ) -> ReconciliationSnapshot:
        with transaction.atomic():
            payment = PaymentRepository.get_for_update(payment_id)

            if not payment.is_pending:
                raise PaymentInvariantViolation(
                    "Only pending Payments can be reconciled."
                )

            if attempt_id is not None:
                attempt = PaymentAttemptRepository.get_for_update(attempt_id)
                if attempt.payment_id != payment.pk:
                    raise PaymentInvariantViolation(
                        "PaymentAttempt does not belong to the expected Payment."
                    )
            else:
                pending_attempts = list(
                    PaymentAttemptRepository.pending_for_payment_for_update(
                        payment.pk,
                    )
                    .filter(authority_id__gt="")
                    .order_by("-attempt_number", "-id")[:2]
                )
                if not pending_attempts:
                    raise PaymentInvariantViolation(
                        "Payment has no pending gateway attempt with an authority."
                    )
                if len(pending_attempts) > 1:
                    raise PaymentInvariantViolation(
                        "Payment has multiple pending gateway attempts."
                    )
                attempt = pending_attempts[0]

            if attempt.status != PaymentAttemptStatus.PENDING:
                raise PaymentInvariantViolation(
                    "Only a pending PaymentAttempt can be reconciled."
                )

            authority_id = cls._normalize(attempt.authority_id)
            if not authority_id:
                raise PaymentInvariantViolation(
                    "PaymentAttempt has no gateway authority."
                )

            return ReconciliationSnapshot(
                payment_id=payment.pk,
                order_id=payment.order_id,
                attempt_id=attempt.pk,
                attempt_number=attempt.attempt_number,
                authority_id=authority_id,
                amount=payment.amount,
                currency=cls._normalize(payment.currency),
                gateway=payment.gateway,
            )

    @classmethod
    def _validate_reconciliation_target(
        cls,
        *,
        payment: PaymentModel,
        attempt: PaymentAttempt,
        snapshot: ReconciliationSnapshot,
    ) -> None:
        if payment.pk != snapshot.payment_id:
            raise PaymentInvariantViolation(
                "Payment identity changed during reconciliation."
            )
        if not payment.is_pending:
            raise PaymentInvariantViolation(
                "Payment changed state while reconciliation was in progress."
            )
        if attempt.pk != snapshot.attempt_id:
            raise PaymentInvariantViolation(
                "PaymentAttempt identity changed during reconciliation."
            )
        if attempt.payment_id != payment.pk:
            raise PaymentInvariantViolation(
                "PaymentAttempt does not belong to the expected Payment."
            )
        if attempt.status != PaymentAttemptStatus.PENDING:
            raise PaymentInvariantViolation(
                "PaymentAttempt changed state while reconciliation was in progress."
            )
        if cls._normalize(attempt.authority_id) != snapshot.authority_id:
            raise PaymentInvariantViolation(
                "PaymentAttempt authority changed during reconciliation."
            )

    @classmethod
    def _validate_inquiry_result(
        cls,
        *,
        result: GatewayInquiryResult,
        snapshot: ReconciliationSnapshot,
    ) -> None:
        if result.gateway != snapshot.gateway:
            raise PaymentInvariantViolation(
                "Payment inquiry gateway does not match the historical Payment gateway."
            )

        if result.amount is not None:
            try:
                amount = Decimal(str(result.amount))
            except (TypeError, ValueError, ArithmeticError) as exc:
                raise PaymentInvariantViolation(
                    "Payment inquiry returned an invalid amount."
                ) from exc
            if amount != snapshot.amount:
                raise PaymentInvariantViolation(
                    "Payment inquiry amount does not match the Payment."
                )

        if result.currency:
            if cls._normalize(result.currency) != snapshot.currency:
                raise PaymentInvariantViolation(
                    "Payment inquiry currency does not match the Payment."
                )

        if result.success and not cls._normalize(result.gateway_reference):
            raise PaymentInvariantViolation(
                "Successful payment inquiry requires a gateway reference."
            )

    @staticmethod
    def _normalize(value: Any) -> str:
        return str(value or "").strip()
