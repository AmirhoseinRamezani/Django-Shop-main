from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import IntegrityError, transaction

from payment.enums import (
    Currency,
    PaymentGateway,
    RefundReason,
    RefundStatus,
)
from payment.exceptions import (
    PaymentCurrencyMismatchError,
    PaymentGatewayError,
    PaymentGatewayNotSupportedError,
    PaymentGatewayRejectedError,
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
        - low-level ORM implementation
        - provider-specific HTTP behavior
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

    Gateway outcome contract:

        definitive rejection
            -> Refund.FAILED

        unknown external outcome
            -> Refund.PENDING

        definitive success + trusted gateway identity
            -> Refund.SUCCESS

    A transport/infrastructure exception is never interpreted as a
    confirmed financial rejection because the gateway may have processed
    the refund before the response was lost.
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

        ``actor`` is intentionally accepted for application-level API
        compatibility and future audit integration. Refund currently does
        not persist actor identity itself.
        """

        del actor

        normalized_amount = cls._normalize_amount(amount)
        normalized_key = cls._normalize_idempotency_key(
            idempotency_key,
        )
        normalized_reason = cls._normalize_reason(reason)
        normalized_reason_detail = cls._normalize_optional(
            reason_detail,
        )

        with transaction.atomic():
            payment = PaymentRepository.get_for_update(
                payment_id,
            )

            # --------------------------------------------
            # Idempotency
            # --------------------------------------------

            existing = (
                RefundRepository.find_by_idempotency_key_for_update(
                    normalized_key,
                )
            )

            if existing is not None:
                cls._validate_idempotent_request(
                    refund=existing,
                    payment=payment,
                    amount=normalized_amount,
                    reason=normalized_reason,
                    reason_detail=normalized_reason_detail,
                )
                return existing

            # --------------------------------------------
            # Payment eligibility
            # --------------------------------------------

            PaymentPolicy.can_refund(payment)

            # --------------------------------------------
            # V1 currency contract
            # --------------------------------------------

            cls._validate_v1_currency(
                payment.currency,
            )

            # --------------------------------------------
            # Cumulative successful refund authorization
            # --------------------------------------------

            successful_refunded = (
                RefundRepository.successful_amount_for_payment(
                    payment.pk,
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

            # --------------------------------------------
            # Domain-level financial validation
            # --------------------------------------------

            refund_snapshot = Refund(
                payment=payment,
                amount=normalized_amount,
                currency=payment.currency,
                idempotency_key=normalized_key,
                reason=normalized_reason,
                reason_detail=normalized_reason_detail,
                status=RefundStatus.PENDING,
                ip_address=ip_address,
                user_agent=user_agent,
                meta=dict(meta or {}),
            )

            refund_snapshot.validate_against_payment(
                payment_amount=payment.amount,
                payment_currency=payment.currency,
            )

            # --------------------------------------------
            # Persist request snapshot
            # --------------------------------------------

            try:
                refund = RefundRepository.create(
                    payment=payment,
                    amount=normalized_amount,
                    currency=payment.currency,
                    idempotency_key=normalized_key,
                    reason=normalized_reason,
                    reason_detail=normalized_reason_detail,
                    status=RefundStatus.PENDING,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    meta=dict(meta or {}),
                )

            except IntegrityError:
                """
                The database uniqueness constraint is authoritative.

                The insert must be isolated inside a savepoint so a
                PostgreSQL IntegrityError does not abort the outer
                application transaction.

                Only an actually resolvable idempotency record is treated
                as an idempotency race. Unrelated integrity failures are
                re-raised.
                """

                existing = cls._resolve_idempotency_race(
                    idempotency_key=normalized_key,
                )

                if existing is None:
                    raise

                cls._validate_idempotent_request(
                    refund=existing,
                    payment=payment,
                    amount=normalized_amount,
                    reason=normalized_reason,
                    reason_detail=normalized_reason_detail,
                )

                return existing

            # --------------------------------------------
            # Gateway execution
            # --------------------------------------------

            try:
                result = GatewayService.refund(
                    payment=payment,
                    refund=refund,
                )

            except PaymentGatewayNotSupportedError:
                return cls._mark_failed(
                    refund=refund,
                    reason=(
                        "Gateway refund operation is not supported."
                    ),
                )

            except PaymentGatewayRejectedError as exc:
                return cls._mark_failed(
                    refund=refund,
                    reason=(
                        cls._normalize_optional(
                            exc.message,
                        )[:255]
                        or "Gateway explicitly rejected the refund."
                    ),
                )

            except PaymentGatewayError as exc:
                """
                Any other normalized gateway exception represents an
                unknown external outcome unless the specific exception
                above proves a deterministic rejection.
                """

                return cls._register_gateway_exception(
                    refund=refund,
                    exc=exc,
                )

            # --------------------------------------------
            # Gateway result contract
            # --------------------------------------------

            if not isinstance(
                result,
                GatewayRefundResult,
            ):
                """
                GatewayService is expected to normalize all provider
                results. A contract violation cannot safely become a
                financial failure because the external financial outcome
                is still unknown.
                """

                return cls._register_gateway_evidence(
                    refund=refund,
                    response_code="INVALID_RESULT_TYPE",
                    gateway_message=(
                        "Gateway returned an invalid refund result."
                    ),
                )

            # --------------------------------------------
            # Gateway identity consistency
            # --------------------------------------------

            if not cls._gateway_matches_payment(
                result=result,
                payment_gateway=payment.gateway,
            ):
                return cls._register_gateway_evidence(
                    refund=refund,
                    response_code=cls._gateway_response_code(
                        result,
                    ),
                    gateway_message=(
                        "Gateway refund result does not match "
                        "the historical Payment gateway."
                    ),
                )

            response_code = cls._gateway_response_code(
                result,
            )
            gateway_message = cls._gateway_message(
                result,
            )
            latency_ms = cls._gateway_latency(
                result,
            )

            # --------------------------------------------
            # Definitive gateway rejection
            # --------------------------------------------

            if not result.success:
                return cls._mark_failed(
                    refund=refund,
                    reason=cls._gateway_failure_reason(
                        result,
                    ),
                    response_code=response_code,
                    gateway_message=gateway_message,
                    latency_ms=latency_ms,
                )

            # --------------------------------------------
            # Successful gateway result must contain trusted identity.
            #
            # Success without identity is NOT financial success.
            # Keep the Refund pending for reconciliation instead.
            # --------------------------------------------

            gateway_reference = (
                cls._normalize_optional(
                    result.gateway_reference,
                )
            )

            gateway_transaction_id = (
                cls._normalize_optional(
                    result.gateway_transaction_id,
                )
            )

            if not (
                gateway_reference
                or gateway_transaction_id
            ):
                return cls._register_gateway_evidence(
                    refund=refund,
                    response_code=response_code,
                    gateway_message=(
                        gateway_message
                        or (
                            "Gateway returned success without "
                            "a refund identity."
                        )
                    ),
                    latency_ms=latency_ms,
                )

            # --------------------------------------------
            # Domain transition
            # --------------------------------------------

            refund.mark_success(
                gateway_reference=gateway_reference,
                gateway_transaction_id=gateway_transaction_id,
                response_code=response_code,
                gateway_message=gateway_message,
                latency_ms=latency_ms,
            )

            RefundRepository.save_success(
                refund,
            )

            # --------------------------------------------
            # Recalculate authoritative successful refund total
            # --------------------------------------------

            successful_refunded = (
                RefundRepository.successful_amount_for_payment(
                    payment.pk,
                )
            )

            cls._validate_successful_refund_total(
                successful_refunded=successful_refunded,
                payment_amount=payment.amount,
            )

            # --------------------------------------------
            # Fully refunded Payment
            # --------------------------------------------

            if successful_refunded == payment.amount:
                payment.refund()

                PaymentRepository.save_refund_state(
                    payment,
                )

            return refund

    # ================================
    # Idempotency
    # ================================

    @staticmethod
    def _resolve_idempotency_race(
        *,
        idempotency_key: str,
    ) -> Refund | None:
        """
        Resolve a concurrent idempotency race after an INSERT conflict.

        The lookup executes after the inner savepoint has rolled back,
        leaving the outer transaction usable.
        """

        with transaction.atomic():
            return (
                RefundRepository.find_by_idempotency_key_for_update(
                    idempotency_key,
                )
            )

    @staticmethod
    def _validate_idempotent_request(
        *,
        refund: Refund,
        payment,
        amount: Decimal,
        reason: str,
        reason_detail: str,
    ) -> None:
        """
        Validate reuse of an existing refund idempotency identity.

        A reused idempotency key must represent the same logical request.
        """

        if refund.payment_id != payment.pk:
            raise PaymentInvariantViolation(
                "Refund idempotency key belongs to another Payment.",
            )

        if refund.amount != amount:
            raise PaymentRefundAmountInvalidError(
                (
                    "Refund idempotency key was already used "
                    "with a different amount."
                ),
            )

        if refund.currency != payment.currency:
            raise PaymentCurrencyMismatchError(
                (
                    "Refund idempotency key was already used "
                    "with a different currency."
                ),
            )

        if refund.reason != reason:
            raise PaymentInvariantViolation(
                (
                    "Refund idempotency key was already used "
                    "with a different reason."
                ),
            )

        if refund.reason_detail != reason_detail:
            raise PaymentInvariantViolation(
                (
                    "Refund idempotency key was already used "
                    "with different reason details."
                ),
            )

    # ================================
    # Financial validation
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

        These belong to V2.
        """

        if currency != Currency.IRR:
            raise PaymentCurrencyMismatchError(
                "Only IRR refunds are supported in V1.",
            )

    @staticmethod
    def _validate_successful_refund_total(
        *,
        successful_refunded: Decimal,
        payment_amount: Decimal,
    ) -> None:
        """
        Validate the authoritative persisted successful-refund aggregate.
        """

        if successful_refunded < Decimal("0"):
            raise PaymentInvariantViolation(
                "Successful refund total cannot be negative.",
            )

        if successful_refunded > payment_amount:
            raise PaymentInvariantViolation(
                (
                    "Existing successful refunds already exceed "
                    "the Payment amount."
                ),
            )

    @staticmethod
    def _validate_requested_amount(
        *,
        amount: Decimal,
        remaining_refundable: Decimal,
    ) -> None:
        """
        Validate the requested refund against remaining balance.
        """

        if remaining_refundable <= Decimal("0"):
            raise PaymentRefundAmountInvalidError(
                "Payment has no refundable balance remaining.",
            )

        if amount > remaining_refundable:
            raise PaymentRefundAmountInvalidError(
                (
                    "Refund amount exceeds the remaining "
                    "refundable balance."
                ),
            )

    # ================================
    # Gateway outcome handling
    # ================================

    @staticmethod
    def _register_gateway_exception(
        *,
        refund: Refund,
        exc: PaymentGatewayError,
    ) -> Refund:
        """
        Keep Refund PENDING when the external outcome is unknown.

        Exception text is not persisted because provider exceptions may
        contain secrets, URLs, headers, tokens, or raw payloads.
        """

        return RefundService._register_gateway_evidence(
            refund=refund,
            response_code=exc.__class__.__name__,
            gateway_message=(
                "Gateway refund execution did not return "
                "a definitive result."
            ),
        )

    @staticmethod
    def _register_gateway_evidence(
        *,
        refund: Refund,
        response_code: str = "",
        gateway_message: str = "",
        latency_ms: int | None = None,
    ) -> Refund:
        """
        Persist safe normalized evidence while keeping Refund PENDING.

        This path is used when the external financial outcome is unknown
        or the provider result cannot safely be promoted to SUCCESS/FAILED.
        """

        refund.register_gateway_response(
            response_code=response_code[:64],
            gateway_message=gateway_message[:255],
        )

        if latency_ms is not None:
            refund.record_latency(
                latency_ms=latency_ms,
            )

        RefundRepository.save_gateway_evidence(
            refund,
        )

        return refund

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

        This must only be used for confirmed failures.
        """

        if refund.is_terminal:
            return refund

        refund.mark_failed(
            reason=reason[:255],
            response_code=response_code[:64],
            gateway_message=gateway_message[:255],
            latency_ms=latency_ms,
        )

        RefundRepository.save_failure(
            refund,
        )

        return refund

    # ================================
    # Gateway result helpers
    # ================================

    @staticmethod
    def _gateway_matches_payment(
        *,
        result: GatewayRefundResult,
        payment_gateway: PaymentGateway | str,
    ) -> bool:
        """
        Ensure the normalized gateway result matches the historical
        Payment gateway.
        """

        result_gateway = result.gateway

        if isinstance(
            result_gateway,
            PaymentGateway,
        ):
            result_gateway = result_gateway.value

        historical_gateway = payment_gateway

        if isinstance(
            historical_gateway,
            PaymentGateway,
        ):
            historical_gateway = historical_gateway.value

        return str(result_gateway) == str(
            historical_gateway,
        )

    @staticmethod
    def _gateway_response_code(
        result: GatewayRefundResult,
    ) -> str:
        return RefundService._normalize_optional(
            result.response_code,
        )[:64]

    @staticmethod
    def _gateway_message(
        result: GatewayRefundResult,
    ) -> str:
        return RefundService._normalize_optional(
            result.message,
        )[:255]

    @staticmethod
    def _gateway_failure_reason(
        result: GatewayRefundResult,
    ) -> str:
        """
        Build a bounded provider-independent failure reason.
        """

        message = RefundService._normalize_optional(
            result.message,
        )

        if message:
            return message[:255]

        response_code = RefundService._normalize_optional(
            result.response_code,
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
        Keep V1 compatible with the current GatewayRefundResult contract.

        The current DTO does not formally require latency_ms, but this
        helper allows a future compatible DTO extension without changing
        the service contract.
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
    # Input normalization
    # ================================

    @staticmethod
    def _normalize_amount(
        amount: Decimal,
    ) -> Decimal:
        """
        Normalize a V1 financial amount without floating-point arithmetic.
        """

        try:
            normalized = Decimal(
                str(amount),
            )
        except (
            TypeError,
            ValueError,
            ArithmeticError,
        ) as exc:
            raise PaymentRefundAmountInvalidError(
                "Invalid refund amount.",
            ) from exc

        if not normalized.is_finite():
            raise PaymentRefundAmountInvalidError(
                "Refund amount must be finite.",
            )

        if normalized <= Decimal("0"):
            raise PaymentRefundAmountInvalidError(
                "Refund amount must be greater than zero.",
            )

        return normalized

    @staticmethod
    def _normalize_reason(
        reason,
    ) -> str:
        """
        Normalize and validate the RefundReason enum value.
        """

        value = getattr(
            reason,
            "value",
            reason,
        )

        normalized = str(
            value or "",
        ).strip()

        allowed = {
            choice.value
            for choice in RefundReason
        }

        if normalized not in allowed:
            raise PaymentInvariantViolation(
                "Invalid refund reason.",
            )

        return normalized

    @staticmethod
    def _normalize_idempotency_key(
        value: str,
    ) -> str:
        """
        Normalize and validate the refund request identity.
        """

        normalized = str(
            value or "",
        ).strip()

        if not normalized:
            raise PaymentInvariantViolation(
                "Refund idempotency key is required.",
            )

        return normalized

    @staticmethod
    def _normalize_optional(
        value: str | None,
    ) -> str:
        return str(
            value or "",
        ).strip()