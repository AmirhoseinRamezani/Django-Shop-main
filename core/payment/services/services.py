# core/payment/services/services.py
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import transaction

from order.models import OrderModel
from payment.enums import Currency, PaymentAttemptStatus, PaymentGateway, PaymentStatusType
from payment.exceptions import (
    PaymentAttemptIdentityConflictError,
    PaymentCreationForbiddenError,
    PaymentGatewayError,
    PaymentInvariantViolation,
)
from payment.models import PaymentAttempt, PaymentModel
from payment.policies import PaymentPolicy
from payment.providers.base import GatewayPaymentResult
from payment.repositories.payment_attempt_repository import PaymentAttemptRepository
from payment.repositories.payment_repository import PaymentRepository
from payment.services.gateway_service import GatewayService


class PaymentService:
    """
    Authoritative application service for payment initiation.

    Transaction boundaries are deliberately split around gateway I/O:

        Phase A:
            Order lock -> policy -> Payment -> Attempt -> commit

        Phase B:
            Gateway HTTP with no database lock/transaction

        Phase C:
            Payment lock -> Attempt lock -> persist gateway identity -> commit

    PaymentAttempt is the owner of gateway execution identity. Payment owns
    the immutable financial snapshot.
    """

    @staticmethod
    def start_payment(
        order: OrderModel,
        *,
        callback_url: str | None = None,
        ip_address: str | None = None,
        user_agent: str = "",
    ) -> str:
        """
        Start exactly one gateway execution cycle for an Order.

        Existing pending Payment/Attempt state is treated idempotently:
        when an authority already exists, no second gateway initiation is
        performed and the existing payment URL is returned.

        If a pending attempt exists without an authority, the operation is
        considered in-flight/unknown and no second gateway request is made.
        Reconciliation can safely resolve that attempt later.
        """

        if order is None or order.pk is None:
            raise PaymentCreationForbiddenError("Order is required.")

        # ==============================================================
        # PHASE A — CREATE / RESOLVE LOCAL PAYMENT EXECUTION
        # ==============================================================
        with transaction.atomic():
            locked_order = (
                OrderModel.objects
                .select_for_update()
                .get(pk=order.pk)
            )

            PaymentPolicy.can_create_payment(locked_order)

            pending_payments = list(
                PaymentRepository.pending_for_order_for_update(
                    locked_order.pk,
                )
            )

            if len(pending_payments) > 1:
                raise PaymentInvariantViolation(
                    "Multiple pending Payments exist for one Order."
                )

            if pending_payments:
                payment = pending_payments[0]
                attempts = list(
                    PaymentAttemptRepository.pending_for_payment_for_update(
                        payment.pk,
                    )
                )

                if len(attempts) > 1:
                    raise PaymentInvariantViolation(
                        "Multiple pending PaymentAttempts exist for one Payment."
                    )

                if attempts:
                    attempt = attempts[0]
                    if attempt.authority_id:
                        authority = attempt.authority_id
                    else:
                        raise PaymentGatewayError(
                            "Payment gateway initiation is already in progress.",
                            details={
                                "payment_id": payment.pk,
                                "attempt_id": attempt.pk,
                                "operation": "initiate_payment",
                            },
                            retryable=True,
                        )
                else:
                    # Compatibility recovery for a pending Payment created by
                    # an older local path. The Payment aggregate remains the
                    # same; only its missing execution Attempt is created.
                    attempt = PaymentAttemptRepository.create(
                        payment=payment,
                        attempt_number=PaymentAttemptRepository.next_attempt_number(
                            payment.pk,
                        ),
                        retry_of=None,
                        retry_count=1,
                        status=PaymentAttemptStatus.PENDING,
                        ip_address=ip_address,
                        user_agent=user_agent or "",
                    )
                    authority = ""
            else:
                selected_gateway = GatewayService.current_gateway()

                amount = Decimal(str(locked_order.final_price))
                payment = PaymentRepository.create(
                    order=locked_order,
                    amount=amount,
                    currency=Currency.IRR,
                    gateway=selected_gateway,
                    status=PaymentStatusType.PENDING,
                )

                attempt = PaymentAttemptRepository.create(
                    payment=payment,
                    attempt_number=1,
                    retry_of=None,
                    retry_count=1,
                    status=PaymentAttemptStatus.PENDING,
                    ip_address=ip_address,
                    user_agent=user_agent or "",
                )
                authority = ""

            payment_id = payment.pk
            attempt_id = attempt.pk
            payment_amount = payment.amount
            payment_currency = str(payment.currency)
            payment_gateway = payment.gateway
            order_id = locked_order.pk

        # ==============================================================
        # PHASE B — EXTERNAL GATEWAY I/O
        # ==============================================================
        if authority:
            return GatewayService.payment_url(
                authority,
                gateway=payment_gateway,
            )

        resolved_callback_url = PaymentService._resolve_callback_url(callback_url)

        try:
            result = GatewayService.initiate_payment(
                amount=payment_amount,
                order_id=str(order_id),
                callback_url=resolved_callback_url,
                currency=payment_currency,
                description=f"Order #{order_id}",
                gateway=payment_gateway,
                metadata={
                    "payment_id": payment_id,
                    "attempt_id": attempt_id,
                },
            )
        except PaymentGatewayError:
            # Transport uncertainty must not be converted into a financial
            # failure. The pending attempt remains available for retry or
            # reconciliation.
            raise

        # ==============================================================
        # PHASE C — PERSIST GATEWAY RESULT
        # ==============================================================
        rejection_error: PaymentGatewayError | None = None
        with transaction.atomic():
            payment = PaymentRepository.get_for_update(payment_id)
            attempt = PaymentAttemptRepository.find_for_update(attempt_id)

            if attempt.payment_id != payment.pk:
                raise PaymentInvariantViolation(
                    "PaymentAttempt does not belong to the expected Payment."
                )

            if not payment.is_pending:
                raise PaymentInvariantViolation(
                    "Payment changed state while gateway initiation was in progress."
                )

            if not attempt.is_pending:
                raise PaymentInvariantViolation(
                    "PaymentAttempt changed state while gateway initiation was in progress."
                )

            PaymentService._persist_initiation_result(
                attempt=attempt,
                result=result,
            )

            if result.success:
                PaymentAttemptRepository.save_gateway_identity(attempt)
                authority = attempt.authority_id
            else:
                attempt.mark_failed(
                    reason=result.message or "Payment gateway rejected initiation.",
                    response_code=result.response_code or "",
                    gateway_message=result.message or "",
                )
                PaymentAttemptRepository.save_failure(attempt)

                payment.fail()
                PaymentRepository.save(
                    payment,
                    update_fields=("status",),
                )
                
                # خطا را آماده کرده ولی داخل این atomic block شلیک نمی‌کنیم
                # تا دیتابیس rollback نشود و وضعیت FAILED ذخیره بماند.
                rejection_error = PaymentGatewayError(
                    result.message or "Payment gateway rejected payment initiation.",
                    details={
                        "payment_id": payment.pk,
                        "attempt_id": attempt.pk,
                        "gateway": str(payment.gateway),
                        "operation": "initiate_payment",
                        "response_code": result.response_code or "",
                    },
                    retryable=False,
                )
        # اگر رد درگاه رخ داده باشد، پس از commit شدن وضعیت FAILED در دیتابیس، استثنا شلیک می‌شود
        if rejection_error is not None:
            raise rejection_error

        # URL generation is pure gateway infrastructure and occurs after the
        # database transaction has committed.
        return GatewayService.payment_url(
            authority,
            gateway=payment_gateway,
        )

    @staticmethod
    def _resolve_callback_url(callback_url: str | None) -> str:
        resolved = str(
            callback_url
            or getattr(settings, "PAYMENT_CALLBACK_URL", "")
            or "",
        ).strip()

        if not resolved:
            raise PaymentGatewayError(
                "Payment callback URL is not configured.",
                details={
                    "setting": "PAYMENT_CALLBACK_URL",
                    "operation": "initiate_payment",
                },
                retryable=False,
            )

        return resolved

    @staticmethod
    def _persist_initiation_result(
        *,
        attempt: PaymentAttempt,
        result: GatewayPaymentResult,
    ) -> None:
        """Apply normalized gateway initiation evidence to an Attempt."""

        authority = str(result.authority or "").strip()
        if result.success and not authority:
            raise PaymentGatewayError(
                "Successful payment initiation requires gateway authority.",
                details={
                    "attempt_id": attempt.pk,
                    "operation": "initiate_payment",
                },
                retryable=False,
            )

        if authority and attempt.authority_id and attempt.authority_id != authority:
            raise PaymentAttemptIdentityConflictError(
                "Gateway authority conflicts with the stored PaymentAttempt identity.",
                details={
                    "attempt_id": attempt.pk,
                },
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
