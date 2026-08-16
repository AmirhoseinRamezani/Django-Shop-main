
# core/payment/services/refund.py

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import IntegrityError, transaction

from payment.enums import Currency, RefundStatus
from payment.exceptions import (
    PaymentCurrencyMismatchError,
    PaymentGatewayError,
    PaymentGatewayNotSupportedError,
    PaymentInvariantViolation,
    PaymentRefundAmountInvalidError,
)
from payment.models.refund import Refund
from payment.policies import PaymentPolicy
from payment.providers.base import GatewayRefundResult
from payment.repositories.payment_repository import PaymentRepository
from payment.repositories.refund_repository import RefundRepository
from payment.services.gateway_service import GatewayService


class RefundService:
    """
    Application service for the Payment refund workflow.

    Responsibilities:
        - transaction boundary
        - canonical Payment locking
        - idempotency resolution
        - cumulative refund authorization
        - Refund creation
        - gateway orchestration
        - Refund domain transitions
        - Refund persistence
        - fully-refunded Payment synchronization

    Non-responsibilities:
        - Refund state-machine rules
        - low-level ORM queries
        - repository locking implementation
        - gateway HTTP/protocol implementation
        - provider-specific response parsing
        - Order mutation
        - event publication
        - raw gateway payload persistence

    Concurrency contract:

        transaction.atomic()
            ->
        lock Payment
            ->
        resolve idempotency
            ->
        authorize cumulative refund
            ->
        create Refund
            ->
        execute gateway
            ->
        persist Refund result
            ->
        synchronize fully-refunded Payment
            ->
        commit

    Payment is the canonical synchronization point for cumulative refund
    authorization.

    Gateway outcome contract:

        definitive rejection
            -> Refund.FAILED

        unknown external outcome
            -> Refund.PENDING

        definitive success + trusted gateway identity
            -> Refund.SUCCESS

    A transport exception is never interpreted as a confirmed gateway
    rejection because the gateway may have accepted the refund before the
    response was lost.
    """

    @classmethod
    def refund(
        cls,
        *,
        payment_id: int,
        amount: Decimal,
        idempotency_key: str,
        reason,
        reason_detail: str = "",
        actor: Any = None,
        ip_address: str | None = None,
        user_agent: str = "",
        meta: dict[str, Any] | None = None,
    ) -> Refund:
        """
        Execute one refund request.

        The complete cumulative financial authorization workflow is
        serialized through the Payment row lock.

        The actor parameter is intentionally accepted as application
        context. Refund persistence does not currently own actor identity.
        """

        del actor

        normalized_amount = cls._normalize_amount(amount)
        normalized_key = cls._normalize_idempotency_key(
            idempotency_key
        )

        with transaction.atomic():
            payment = PaymentRepository.get_for_update(
                payment_id
            )

            # ------------------------------------
            # Idempotency
            # ------------------------------------

            existing = (
                RefundRepository.find_by_idempotency_key_for_update(
                    normalized_key
                )
            )

            if existing is not None:
                cls._validate_idempotent_request(
                    refund=existing,
                    payment=payment,
                    amount=normalized_amount,
                )
                return existing

            # ------------------------------------
            # Payment eligibility
            # ------------------------------------

            PaymentPolicy.can_refund(payment)

            # ------------------------------------
            # V1 currency contract
            # ------------------------------------

            cls._validate_v1_currency(
                payment.currency
            )

            # ------------------------------------
            # Cumulative successful refund authorization
            # ------------------------------------

            successful_refunded = (
                RefundRepository.successful_amount_for_payment(
                    payment.pk
                )
            )

            cls._validate_successful_refund_total(
                successful_refunded=successful_refunded,
                payment_amount=payment.amount,
            )

            remaining_refundable = (
                payment.amount - successful_refunded
            )

            cls._validate_requested_amount(
                amount=normalized_amount,
                remaining_refundable=remaining_refundable,
            )

            # ------------------------------------
            # Immutable Refund snapshot
            # ------------------------------------

            try:
                refund = RefundRepository.create(
                    payment=payment,
                    amount=normalized_amount,
                    currency=payment.currency,
                    idempotency_key=normalized_key,
                    reason=reason,
                    reason_detail=reason_detail,
                    status=RefundStatus.PENDING,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    meta=meta or {},
                )
            except IntegrityError:
                """
                The database uniqueness constraint is authoritative.

                An IntegrityError is interpreted as an idempotency race
                only if the idempotency record can actually be resolved.

                Unrelated database integrity failures are re-raised.
                """

                existing = (
                    RefundRepository.find_by_idempotency_key_for_update(
                        normalized_key
                    )
                )

                if existing is None:
                    raise

                cls._validate_idempotent_request(
                    refund=existing,
                    payment=payment,
                    amount=normalized_amount,
                )

                return existing

            # ------------------------------------
            # Domain financial validation
            # ------------------------------------

            refund.validate_against_payment(
                payment_amount=payment.amount,
                payment_currency=payment.currency,
            )

            # ------------------------------------
            # Request observability
            # ------------------------------------

            RefundRepository.save(
                refund,
                update_fields=(
                    "ip_address",
                    "user_agent",
                    "meta",
                ),
            )

            # ------------------------------------
            # Gateway execution
            # ------------------------------------

            try:
                result = GatewayService.refund(
                    payment=payment,
                    refund=refund,
                )

            except PaymentGatewayNotSupportedError:
                """
                Capability failure is deterministic.

                The selected gateway explicitly cannot perform refunds,
                therefore this request can safely become FAILED.
                """

                return cls._mark_failed(
                    refund=refund,
                    reason=(
                        "Gateway refund operation is not supported."
                    ),
                )

            except PaymentGatewayError as exc:
                """
                PaymentGatewayError does not necessarily prove rejection.

                GatewayService may raise this for:
                    - timeout
                    - connection failure
                    - provider unavailability
                    - lost response
                    - infrastructure failure

                Therefore the financial outcome remains unknown and the
                Refund stays PENDING for reconciliation.
                """

                return cls._register_gateway_exception(
                    refund=refund,
                    exc=exc,
                )

            except Exception as exc:
                """
                Unknown infrastructure failure.

                Never manufacture a terminal financial failure from an
                exception whose external financial outcome is unknown.
                """

                return cls._register_gateway_exception(
                    refund=refund,
                    exc=exc,
                )

            # ------------------------------------
            # Gateway result validation
            # ------------------------------------

            if not isinstance(
                result,
                GatewayRefundResult,
            ):
                return cls._mark_failed(
                    refund=refund,
                    reason=(
                        "Gateway returned an invalid refund result."
                    ),
                )

            # ------------------------------------
            # Gateway definitive failure
            # ------------------------------------

            if not result.success:
                return cls._mark_failed(
                    refund=refund,
                    reason=cls._gateway_failure_reason(
                        result
                    ),
                    response_code=cls._gateway_response_code(
                        result
                    ),
                    gateway_message=cls._gateway_message(
                        result
                    ),
                )

            # ------------------------------------
            # Gateway SUCCESS identity
            # ------------------------------------

            gateway_reference = (
                cls._normalize_optional(
                    result.gateway_reference
                )
            )

            gateway_transaction_id = (
                cls._normalize_optional(
                    result.gateway_transaction_id
                )
            )

            if not (
                gateway_reference
                or gateway_transaction_id
            ):
                """
                A success result without an external identity cannot be
                safely reconciled.

                It is intentionally not converted into SUCCESS.

                The provider contract has returned a logically successful
                result, but the Payment Core lacks a trusted external
                identity. This is treated as a deterministic integration
                failure in V1.
                """

                return cls._mark_failed(
                    refund=refund,
                    reason=(
                        "Gateway returned success without "
                        "a gateway refund identity."
                    ),
                    response_code=cls._gateway_response_code(
                        result
                    ),
                    gateway_message=cls._gateway_message(
                        result
                    ),
                )

            # ------------------------------------
            # Domain transition
            # ------------------------------------

            refund.mark_success(
                gateway_reference=gateway_reference,
                gateway_transaction_id=gateway_transaction_id,
                response_code=cls._gateway_response_code(
                    result
                ),
                gateway_message=cls._gateway_message(
                    result
                ),
                latency_ms=cls._gateway_latency(
                    result
                ),
            )

            RefundRepository.save_success(
                refund
            )

            # ------------------------------------
            # Recalculate authoritative successful total
            # ------------------------------------

            successful_refunded = (
                RefundRepository.successful_amount_for_payment(
                    payment.pk
                )
            )

            cls._validate_successful_refund_total(
                successful_refunded=successful_refunded,
                payment_amount=payment.amount,
            )

            # ------------------------------------
            # Fully refunded Payment
            # ------------------------------------

            if successful_refunded == payment.amount:
                payment.refund()

                PaymentRepository.save_refund_state(
                    payment
                )

            return refund

    # ================================
    # IDEMPOTENCY
    # ================================

    @staticmethod
    def _validate_idempotent_request(
        *,
        refund: Refund,
        payment,
        amount: Decimal,
    ) -> None:
        """
        Validate reuse of an existing idempotency key.
        The same key is valid only for the same Payment financial
        operation.

        The database guarantees global uniqueness of the key. Therefore
        association with another Payment is an application-level conflict.
        """

        if refund.payment_id != payment.pk:
            raise PaymentInvariantViolation(
                "Refund idempotency key belongs to another Payment."
            )

        if refund.amount != amount:
            raise PaymentRefundAmountInvalidError(
                (
                    "Refund idempotency key was already used with "
                    "a different refund amount."
                )
            )

        if refund.currency != payment.currency:
            raise PaymentCurrencyMismatchError(
                (
                    "Refund idempotency key was already used with "
                    "a different refund currency."
                )
            )

    # ================================
    # FINANCIAL VALIDATION
    # ================================

    @staticmethod
    def _validate_v1_currency(
        currency: str,
    ) -> None:
        """
        Enforce the V1 IRR-only financial contract.

        V1 deliberately avoids:
            - FX conversion
            - multi-currency arithmetic
            - fractional currency units
            - exchange-rate snapshots

        These belong to V2 and can be introduced as an extension of the
        existing Payment/Refund contracts rather than a rewrite.
        """

        if currency != Currency.IRR:
            raise PaymentCurrencyMismatchError(
                "Only IRR refunds are supported in V1."
            )

    @staticmethod
    def _validate_successful_refund_total(
        *,
        successful_refunded: Decimal,
        payment_amount: Decimal,
    ) -> None:
        """
        Validate the authoritative persisted successful-refund aggregate.

        This is an integrity assertion, not the refund authorization rule.
        """

        if successful_refunded < Decimal("0"):
            raise PaymentInvariantViolation(
                "Successful refund total cannot be negative."
            )

        if successful_refunded > payment_amount:
            raise PaymentInvariantViolation(
                (
                    "Existing successful refunds already exceed "
                    "the Payment amount."
                )
            )

    @staticmethod
    def _validate_requested_amount(
        *,
        amount: Decimal,
        remaining_refundable: Decimal,
    ) -> None:
        """
        Validate the requested refund against the currently available
        refundable balance.
        """

        if remaining_refundable <= Decimal("0"):
            raise PaymentRefundAmountInvalidError(
                "Payment has no refundable balance remaining."
            )

        if amount > remaining_refundable:
            raise PaymentRefundAmountInvalidError(
                (
                    "Refund amount exceeds the remaining "
                    "refundable balance."
                )
            )

    # ================================
    # GATEWAY EXCEPTION / UNKNOWN OUTCOME
    # ================================

    @staticmethod
    def _register_gateway_exception(
        *,
        refund: Refund,
        exc: Exception,
    ) -> Refund:
        """
        Preserve safe evidence for an unknown gateway outcome.

        The exception text itself is deliberately not persisted because
        provider exceptions may contain:
            - credentials
            - request payloads
            - URLs
            - headers
            - provider responses
            - sensitive data

        GatewayLog/reconciliation infrastructure remains responsible for
        technical gateway evidence.

        Refund remains PENDING.
        """

        refund.register_gateway_response(
            response_code=exc.__class__.__name__,
            gateway_message=(
                "Gateway refund execution did not return "
                "a definitive result."
            ),
        )

        RefundRepository.save_gateway_evidence(
            refund
        )

        return refund

    # ================================
    # TERMINAL FAILURE
    # ================================

    @staticmethod
    def _mark_failed(
        *,
        refund: Refund,
        reason: str,
        response_code: str = "",
        gateway_message: str = "",
        latency_ms: int | None = None,
    ) -> Refund:
        """
        Persist a deterministic terminal FAILED transition.

        This method is intentionally restricted to known failures.

        It must not be used for:
            - timeout
            - connection reset
            - lost response
            - provider unavailability
            - other unknown external outcomes
        """

        if refund.is_terminal:
            return refund

        refund.mark_failed(
            reason=reason,
            response_code=response_code,
            gateway_message=gateway_message,
            latency_ms=latency_ms,
        )

        RefundRepository.save_failure(
            refund
        )

        return refund

    # ================================
    # GATEWAY RESULT NORMALIZATION
    # ================================

    @staticmethod
    def _gateway_response_code(
        result: GatewayRefundResult,
    ) -> str:
        """
        Return the normalized provider-independent response code.
        """

        return RefundService._normalize_optional(
            result.response_code
        )[:64]

    @staticmethod
    def _gateway_message(
        result: GatewayRefundResult,
    ) -> str:
        """
        Return the normalized provider-independent gateway message.
        """

        return RefundService._normalize_optional(
            result.message
        )[:255]

    @staticmethod
    def _gateway_failure_reason(
        result: GatewayRefundResult,
    ) -> str:
        """
        Build a deterministic, bounded failure reason.

        Raw provider payloads are intentionally excluded.
        """

        message = RefundService._normalize_optional(
            result.message
        )

        if message:
            return message[:255]

        response_code = RefundService._normalize_optional(
            result.response_code
        )

        if response_code:
            return (
                f"Gateway refund failed: {response_code}"
            )[:255]

        return "Gateway refund failed."

    @staticmethod
    def _gateway_latency(
        result: GatewayRefundResult,
    ) -> int | None:
        """
        GatewayRefundResult currently does not define latency_ms.

        Keep the service compatible with the existing typed gateway
        contract while allowing a future extended result object to expose
        latency without making V1 depend on it.
        """

        value = getattr(
            result,
            "latency_ms",
            None,
        )

        if value is None:
            return None

        try:
            normalized = int(value)
        except (
            TypeError,
            ValueError,
        ):
            return None

        return max(
            0,
            normalized,
        )

    # ================================
    # INPUT NORMALIZATION
    # ================================

    @staticmethod
    def _normalize_amount(
        amount: Decimal,
    ) -> Decimal:
        """
        Normalize a financial amount without floating-point arithmetic.
        """

        try:
            normalized = Decimal(
                str(amount)
            )
        except (
            TypeError,
            ValueError,
            ArithmeticError,
        ) as exc:
            raise PaymentRefundAmountInvalidError(
                "Invalid refund amount."
            ) from exc

        if not normalized.is_finite():
            raise PaymentRefundAmountInvalidError(
                "Refund amount must be finite."
            )

        if normalized <= Decimal("0"):
            raise PaymentRefundAmountInvalidError(
                "Refund amount must be greater than zero."
            )

        return normalized

    @staticmethod
    def _normalize_idempotency_key(
        value: str,
    ) -> str:
        """
        Normalize and validate the logical refund request identity.
        """

        normalized = str(
            value or ""
        ).strip()

        if not normalized:
            raise PaymentInvariantViolation(
                "Refund idempotency key is required."
            )

        return normalized

    @staticmethod
    def _normalize_optional(
        value: str | None,
    ) -> str:
        return str(
            value or ""
        ).strip()