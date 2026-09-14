# core/payment/services/retry.py
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from order.models import OrderModel
from payment.enums import PaymentAttemptStatus, PaymentStatusType
from payment.exceptions import PaymentGatewayError, PaymentInvariantViolation
from payment.models import PaymentAttempt, PaymentModel
from payment.policies import PaymentAttemptPolicy, PaymentPolicy
from payment.providers.base import GatewayPaymentResult
from payment.repositories.payment_attempt_repository import (
    PaymentAttemptRepository,
)
from payment.repositories.payment_repository import PaymentRepository
from payment.services.gateway_service import GatewayService


@dataclass(frozen=True, slots=True)
class RetrySnapshot:
    payment_id: int
    attempt_id: int
    payment_amount: Decimal
    payment_currency: str
    payment_gateway: str
    order_id: int
    callback_url: str


class RetryPaymentService:
    """
    Retry one gateway execution for the existing Payment aggregate.

    The local retry transaction is deliberately committed before gateway I/O.
    """

    @staticmethod
    def retry(
        *,
        order: OrderModel,
        callback_url: str,
        ip_address: str | None = None,
        user_agent: str = "",
    ) -> str:
        snapshot, existing_authority = RetryPaymentService._prepare_retry(
            order=order,
            callback_url=callback_url,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        if existing_authority:
            return GatewayService.payment_url(
                existing_authority,
                gateway=snapshot.payment_gateway,
            )

        try:
            result = GatewayService.initiate_payment(
                amount=snapshot.payment_amount,
                order_id=str(snapshot.order_id),
                callback_url=snapshot.callback_url,
                currency=snapshot.payment_currency,
                description=f"Order #{snapshot.order_id}",
                gateway=snapshot.payment_gateway,
                metadata={
                    "payment_id": snapshot.payment_id,
                    "attempt_id": snapshot.attempt_id,
                },
            )
        except PaymentGatewayError:
            # Transport uncertainty must leave the Attempt pending.
            raise

        rejection_error: PaymentGatewayError | None = None

        with transaction.atomic():
            payment = PaymentRepository.get_for_update(
                snapshot.payment_id,
            )
            retry_attempt = PaymentAttemptRepository.find_for_update(
                snapshot.attempt_id,
            )

            if retry_attempt is None:
                raise PaymentInvariantViolation(
                    "PaymentAttempt no longer exists."
                )

            if retry_attempt.payment_id != payment.pk:
                raise PaymentInvariantViolation(
                    "PaymentAttempt does not belong to the expected Payment."
                )

            if payment.status != PaymentStatusType.PENDING:
                raise PaymentInvariantViolation(
                    "Payment changed state while retry initiation was in progress."
                )

            if retry_attempt.status != PaymentAttemptStatus.PENDING:
                raise PaymentInvariantViolation(
                    "PaymentAttempt changed state while retry initiation was in progress."
                )

            RetryPaymentService._persist_initiation_result(
                attempt=retry_attempt,
                result=result,
            )

            if result.success:
                PaymentAttemptRepository.save_gateway_identity(
                    retry_attempt,
                )
                authority = retry_attempt.authority_id
            else:
                retry_attempt.mark_failed(
                    reason=result.message
                    or "Payment gateway rejected retry initiation.",
                    response_code=result.response_code or "",
                    gateway_message=result.message or "",
                )
                PaymentAttemptRepository.save_failure(
                    retry_attempt,
                )

                # The Payment aggregate remains PENDING: only this execution
                # cycle has a definitive failure.
                rejection_error = PaymentGatewayError(
                    result.message
                    or "Payment gateway rejected retry initiation.",
                    details={
                        "payment_id": payment.pk,
                        "attempt_id": retry_attempt.pk,
                        "gateway": str(payment.gateway),
                        "operation": "retry_payment",
                        "response_code": result.response_code or "",
                    },
                    retryable=False,
                )
                authority = ""

        if rejection_error is not None:
            raise rejection_error

        return GatewayService.payment_url(
            authority,
            gateway=snapshot.payment_gateway,
        )

    @staticmethod
    @transaction.atomic
    def _prepare_retry(
        *,
        order: OrderModel,
        callback_url: str,
        ip_address: str | None,
        user_agent: str,
    ) -> tuple[RetrySnapshot, str]:
        locked_order = (
            OrderModel.objects
            .select_for_update()
            .get(pk=order.pk)
        )

        if not locked_order.is_payable:
            raise ValidationError(_("This order cannot be paid again."))

        pending_payments = list(
            PaymentRepository.pending_for_order_for_update(
                locked_order.pk,
            )
        )

        if len(pending_payments) != 1:
            raise PaymentInvariantViolation(
                "Retry requires exactly one pending Payment."
            )

        payment = pending_payments[0]
        PaymentPolicy.can_retry(payment)

        pending_attempts = list(
            PaymentAttemptRepository.pending_for_payment_for_update(
                payment.pk,
            )
        )

        if len(pending_attempts) > 1:
            raise PaymentInvariantViolation(
                "Multiple pending PaymentAttempts exist for one Payment."
            )

        if pending_attempts:
            pending_attempt = pending_attempts[0]

            snapshot = RetrySnapshot(
                payment_id=payment.pk,
                attempt_id=pending_attempt.pk,
                payment_amount=payment.amount,
                payment_currency=str(payment.currency),
                payment_gateway=str(payment.gateway),
                order_id=locked_order.pk,
                callback_url=str(callback_url).strip(),
            )

            if pending_attempt.authority_id:
                return snapshot, pending_attempt.authority_id

            raise PaymentGatewayError(
                "Payment gateway initiation is already in progress.",
                details={
                    "payment_id": payment.pk,
                    "attempt_id": pending_attempt.pk,
                    "operation": "retry_payment",
                },
                retryable=True,
            )

        previous_attempt = PaymentAttemptRepository.latest_for_payment(
            payment.pk,
        )

        if previous_attempt is None:
            raise PaymentInvariantViolation(
                "Cannot retry a Payment without a previous PaymentAttempt."
            )

        PaymentAttemptPolicy.can_retry(previous_attempt)

        attempt_number = PaymentAttemptRepository.next_attempt_number(
            payment.pk,
        )

        retry_attempt = PaymentAttemptRepository.create(
            payment=payment,
            attempt_number=attempt_number,
            retry_of=previous_attempt,
            retry_count=attempt_number,
            status=PaymentAttemptStatus.PENDING,
            ip_address=ip_address,
            user_agent=user_agent or "",
        )

        return (
            RetrySnapshot(
                payment_id=payment.pk,
                attempt_id=retry_attempt.pk,
                payment_amount=payment.amount,
                payment_currency=str(payment.currency),
                payment_gateway=str(payment.gateway),
                order_id=locked_order.pk,
                callback_url=str(callback_url).strip(),
            ),
            "",
        )

    @staticmethod
    def _persist_initiation_result(
        *,
        attempt: PaymentAttempt,
        result: GatewayPaymentResult,
    ) -> None:
        authority = str(result.authority or "").strip()

        if result.success and not authority:
            raise PaymentGatewayError(
                "Successful payment initiation requires gateway authority.",
                details={
                    "attempt_id": attempt.pk,
                    "operation": "retry_payment",
                },
                retryable=False,
            )

        if authority and attempt.authority_id and attempt.authority_id != authority:
            raise PaymentInvariantViolation(
                "Gateway authority conflicts with the PaymentAttempt identity."
            )

        if authority:
            attempt.authority_id = authority

        if result.gateway_reference:
            attempt.gateway_reference = str(result.gateway_reference).strip()

        if result.gateway_transaction_id:
            attempt.gateway_transaction_id = str(
                result.gateway_transaction_id
            ).strip()

        attempt.register_gateway_response(
            response_code=result.response_code or "",
            gateway_message=result.message or "",
        )
