from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from django.conf import settings

from payment.enums import Currency, PaymentAttemptStatus, PaymentGateway
from payment.exceptions import (
    PaymentAmountMismatchError,
    PaymentCurrencyMismatchError,
    PaymentGatewayError,
    PaymentGatewayMismatchError,
    PaymentGatewayNotSupportedError,
)
from payment.gateways.registry import GatewayRegistry
from payment.providers.base import (
    GatewayCallback,
    GatewayInquiryRequest,
    GatewayInquiryResult,
    GatewayPaymentRequest,
    GatewayPaymentResult,
    GatewayRefundRequest,
    GatewayRefundResult,
    GatewayReverseRequest,
    GatewayReverseResult,
    GatewaySettlementRequest,
    GatewaySettlementResult,
    GatewayVerificationRequest,
    GatewayVerificationResult,
)


class GatewayService:
    """
    Provider-independent gateway orchestration facade.

    ================================
    ARCHITECTURAL RESPONSIBILITY
    ================================

    This service is the boundary between the Payment application layer
    and concrete gateway providers.

    Responsibilities
    ----------------
    - gateway normalization
    - gateway resolution
    - gateway client construction
    - provider-independent request construction
    - provider operation execution
    - normalized result contract validation
    - gateway identity validation
    - gateway amount/currency evidence validation
    - infrastructure exception normalization
    - capability validation

    Non-responsibilities
    --------------------
    - database access
    - transaction.atomic()
    - repository access
    - select_for_update()
    - Payment persistence
    - Payment state transitions
    - PaymentAttempt persistence
    - Refund persistence
    - refund authorization
    - Order mutation
    - coupon mutation
    - inventory mutation
    - event publication
    - outbox creation
    - idempotency persistence
    - retry scheduling
    - business authorization
    - provider-specific parsing

    Canonical architecture
    ----------------------

        Application Service
                |
                v
        GatewayService
                |
                v
        GatewayRegistry
                |
                v
        Concrete BaseGateway
                |
                v
        External Provider

    IMPORTANT
    ---------

    Payment is the financial aggregate.

    PaymentAttempt owns gateway execution identity:

        authority_id
        gateway_reference
        gateway_transaction_id

    Therefore historical gateway operations MUST NOT obtain
    authority_id from Payment.

    For verification/refund:

        Payment
            +
        PaymentAttempt
            |
            +--> gateway identity

    This prevents the Payment aggregate from becoming polluted
    with attempt-level gateway execution state.
    """

    # ================================
    # CONSTANTS
    # ================================

    _OP_INITIATE = "initiate_payment"
    _OP_PAYMENT_URL = "payment_url"
    _OP_VERIFY = "verify"
    _OP_REFUND = "refund"
    _OP_SETTLEMENT = "settlement"
    _OP_REVERSE = "reverse"
    _OP_INQUIRY = "inquiry"
    _OP_CALLBACK = "callback"

    # ================================
    # GATEWAY RESOLUTION
    # ================================

    @classmethod
    def current_gateway(cls) -> PaymentGateway:
        """
        Return the configured default gateway.

        This method is valid only for operations that do not yet have
        a historical gateway snapshot.

        Historical Payment operations MUST use Payment.gateway.
        """

        configured = getattr(
            settings,
            "DEFAULT_PAYMENT_GATEWAY",
            None,
        )

        return cls._normalize_gateway(configured)

    @classmethod
    def _normalize_gateway(
        cls,
        gateway: PaymentGateway | str | None,
    ) -> PaymentGateway:
        """
        Normalize a gateway identifier.

        None means:

            DEFAULT_PAYMENT_GATEWAY

        Unknown values are rejected.
        """

        if gateway is None:
            configured = getattr(
                settings,
                "DEFAULT_PAYMENT_GATEWAY",
                None,
            )

            if configured is None:
                raise PaymentGatewayNotSupportedError(
                    "No default payment gateway is configured.",
                    details={
                        "setting": "DEFAULT_PAYMENT_GATEWAY",
                    },
                )

            gateway = configured

        if isinstance(gateway, PaymentGateway):
            return gateway

        try:
            return PaymentGateway(str(gateway).strip())
        except (TypeError, ValueError) as exc:
            raise PaymentGatewayNotSupportedError(
                "Unsupported payment gateway.",
                details={
                    "gateway": str(gateway),
                },
            ) from exc

    @classmethod
    def is_supported(
        cls,
        gateway: PaymentGateway | str | None,
    ) -> bool:
        """
        Return whether a concrete implementation is registered.

        This is an availability/registration check.

        It does NOT mean that the gateway is operationally healthy.
        """

        try:
            normalized = cls._normalize_gateway(gateway)
        except PaymentGatewayError:
            return False

        try:
            return GatewayRegistry.is_registered(
                normalized,
            )
        except PaymentGatewayError:
            return False

    @classmethod
    def registered_gateways(
        cls,
    ) -> tuple[PaymentGateway, ...]:
        """
        Return all currently registered gateways.
        """

        return GatewayRegistry.gateways()

    @classmethod
    def _client(
        cls,
        gateway: PaymentGateway | str | None = None,
    ) -> Any:
        """
        Resolve and instantiate the concrete gateway client.

        The registry returns a class.

        GatewayService owns client construction.

        No database access occurs here.
        """

        normalized = cls._normalize_gateway(
            gateway,
        )

        try:
            client_class = GatewayRegistry.resolve(
                normalized,
            )
        except PaymentGatewayError:
            raise
        except Exception as exc:
            raise PaymentGatewayError(
                "Failed to resolve payment gateway.",
                details={
                    "gateway": normalized.value,
                    "operation": "gateway_resolution",
                },
                retryable=False,
            ) from exc

        try:
            client = client_class()
        except PaymentGatewayError:
            raise
        except Exception as exc:
            raise PaymentGatewayError(
                "Failed to initialize payment gateway client.",
                details={
                    "gateway": normalized.value,
                    "operation": "gateway_client_initialization",
                },
                retryable=False,
            ) from exc

        return client

    @classmethod
    def _require_capability(
        cls,
        *,
        client: Any,
        gateway: PaymentGateway,
        operation: str,
    ) -> None:
        """
        Verify optional gateway capability.

        BaseGateway exposes supports(), but this helper also protects
        the service from malformed/non-conforming clients.
        """

        try:
            supported = bool(
                client.supports(
                    operation,
                )
            )
        except Exception as exc:
            raise PaymentGatewayError(
                "Failed to determine gateway capability.",
                details={
                    "gateway": gateway.value,
                    "operation": operation,
                },
                retryable=False,
            ) from exc

        if not supported:
            raise PaymentGatewayNotSupportedError(
                "Selected payment gateway does not support this operation.",
                details={
                    "gateway": gateway.value,
                    "operation": operation,
                },
            )

    # ================================
    # PAYMENT INITIATION
    # ================================

    @classmethod
    def initiate_payment(
        cls,
        *,
        amount: Decimal,
        order_id: str,
        callback_url: str,
        currency: str = Currency.IRR,
        description: str = "",
        metadata: Mapping[str, Any] | None = None,
        gateway: PaymentGateway | str | None = None,
    ) -> GatewayPaymentResult:
        """
        Initiate a new gateway payment.

        IMPORTANT:

        This method does NOT create Payment or PaymentAttempt.

        The application service is responsible for:

            Payment creation
                ->
            Attempt creation
                ->
            gateway initiation
                ->
            Attempt identity persistence

        The returned authority/reference must be persisted into the
        corresponding PaymentAttempt by the application workflow.
        """

        normalized_gateway = cls._normalize_gateway(
            gateway,
        )

        client = cls._client(
            normalized_gateway,
        )

        normalized_amount = cls._normalize_amount(
            amount,
            operation=cls._OP_INITIATE,
        )

        normalized_order_id = cls._normalize_required_string(
            order_id,
            field_name="Order ID",
            details={
                "gateway": normalized_gateway.value,
                "operation": cls._OP_INITIATE,
            },
        )

        normalized_callback_url = cls._normalize_required_string(
            callback_url,
            field_name="Callback URL",
            details={
                "gateway": normalized_gateway.value,
                "operation": cls._OP_INITIATE,
            },
        )

        normalized_currency = cls._normalize_currency(
            currency,
        )

        request = GatewayPaymentRequest(
            amount=normalized_amount,
            order_id=normalized_order_id,
            callback_url=normalized_callback_url,
            currency=normalized_currency,
            description=str(
                description or "",
            ).strip(),
            metadata=dict(
                metadata or {},
            ),
        )

        try:
            result = client.initiate_payment(
                request,
            )
        except PaymentGatewayError:
            raise
        except Exception as exc:
            raise PaymentGatewayError(
                "Payment gateway request failed.",
                details={
                    "gateway": normalized_gateway.value,
                    "operation": cls._OP_INITIATE,
                },
                retryable=True,
            ) from exc

        cls._require_result_type(
            result=result,
            expected_type=GatewayPaymentResult,
            gateway=normalized_gateway,
            operation=cls._OP_INITIATE,
        )

        cls._validate_payment_result(
            result=result,
            expected_gateway=normalized_gateway,
            operation=cls._OP_INITIATE,
        )

        return result

    # ================================
    # PAYMENT URL
    # ================================

    @classmethod
    def payment_url(
        cls,
        authority: str,
        *,
        gateway: PaymentGateway | str | None = None,
    ) -> str:
        """
        Build the user-facing gateway payment URL.

        No database access.
        No state mutation.
        """

        normalized_gateway = cls._normalize_gateway(
            gateway,
        )

        normalized_authority = cls._normalize_required_string(
            authority,
            field_name="Payment authority",
            details={
                "gateway": normalized_gateway.value,
                "operation": cls._OP_PAYMENT_URL,
            },
        )

        client = cls._client(
            normalized_gateway,
        )

        try:
            result = client.payment_url(
                normalized_authority,
            )
        except PaymentGatewayError:
            raise
        except Exception as exc:
            raise PaymentGatewayError(
                "Failed to generate payment gateway URL.",
                details={
                    "gateway": normalized_gateway.value,
                    "operation": cls._OP_PAYMENT_URL,
                },
                retryable=False,
            ) from exc

        if not isinstance(
            result,
            str,
        ):
            raise PaymentGatewayError(
                "Gateway returned an invalid payment URL.",
                details={
                    "gateway": normalized_gateway.value,
                    "operation": cls._OP_PAYMENT_URL,
                },
                retryable=False,
            )

        normalized_url = result.strip()

        if not normalized_url:
            raise PaymentGatewayError(
                "Gateway returned an empty payment URL.",
                details={
                    "gateway": normalized_gateway.value,
                    "operation": cls._OP_PAYMENT_URL,
                },
                retryable=False,
            )

        return normalized_url

    # ================================
    # PAYMENT VERIFICATION
    # ================================

    @classmethod
    def verify(
        cls,
        *,
        payment: Any,
        attempt: Any,
    ) -> GatewayVerificationResult:
        """
        Verify a Payment through its historical PaymentAttempt.

        CRITICAL ARCHITECTURAL RULE
        ---------------------------

        authority_id belongs to PaymentAttempt.

        NEVER:

            payment.authority_id

        ALWAYS:

            attempt.authority_id

        Payment provides the immutable financial snapshot:

            amount
            currency
            order

        PaymentAttempt provides gateway execution identity:

            authority_id

        The application service remains responsible for locking and
        persistence around this operation.
        """

        cls._validate_payment_attempt_pair(
            payment=payment,
            attempt=attempt,
        )

        normalized_gateway = cls._payment_gateway(
            payment,
        )

        client = cls._client(
            normalized_gateway,
        )

        amount = cls._normalize_amount(
            getattr(
                payment,
                "amount",
                None,
            ),
            operation=cls._OP_VERIFY,
        )

        currency = cls._normalize_currency(
            getattr(
                payment,
                "currency",
                None,
            ),
        )

        authority = cls._attempt_authority(
            attempt,
            operation=cls._OP_VERIFY,
        )

        order_id = cls._payment_order_id(
            payment,
        )

        request = GatewayVerificationRequest(
            amount=amount,
            authority=authority,
            order_id=order_id,
            currency=currency,
        )

        try:
            result = client.verify_payment(
                request,
            )
        except PaymentGatewayError:
            raise
        except Exception as exc:
            raise PaymentGatewayError(
                "Payment gateway verification failed.",
                details={
                    "gateway": normalized_gateway.value,
                    "operation": cls._OP_VERIFY,
                    "payment_id": getattr(
                        payment,
                        "pk",
                        None,
                    ),
                    "attempt_id": getattr(
                        attempt,
                        "pk",
                        None,
                    ),
                },
                retryable=True,
            ) from exc

        cls._require_result_type(
            result=result,
            expected_type=GatewayVerificationResult,
            gateway=normalized_gateway,
            operation=cls._OP_VERIFY,
            payment_id=getattr(
                payment,
                "pk",
                None,
            ),
            attempt_id=getattr(
                attempt,
                "pk",
                None,
            ),
        )

        cls._validate_verification_result(
            result=result,
            payment=payment,
            attempt=attempt,
            expected_gateway=normalized_gateway,
        )

        return result

    # ================================
    # REFUND
    # ================================

    @classmethod
    def refund(
        cls,
        *,
        payment: Any,
        attempt: Any,
        refund: Any,
        gateway: PaymentGateway | str | None = None,
    ) -> GatewayRefundResult:
        """
        Execute a refund through the historical payment gateway.

        Gateway identity source:

            Payment.gateway

        Gateway execution identity source:

            PaymentAttempt.authority_id

        Refund itself supplies:

            amount
            currency
            refund reference

        This method does NOT authorize whether the refund amount is
        available.

        Cumulative refund authorization belongs to the Refund Service
        while the canonical Payment row is locked.
        """

        cls._validate_payment_attempt_pair(
            payment=payment,
            attempt=attempt,
        )

        payment_gateway = cls._payment_gateway(
            payment,
        )

        if gateway is not None:
            requested_gateway = cls._normalize_gateway(
                gateway,
            )

            if requested_gateway != payment_gateway:
                raise PaymentGatewayMismatchError(
                    "Refund gateway does not match the historical Payment gateway.",
                    details={
                        "payment_id": getattr(
                            payment,
                            "pk",
                            None,
                        ),
                        "payment_gateway": payment_gateway.value,
                        "requested_gateway": requested_gateway.value,
                        "operation": cls._OP_REFUND,
                    },
                )

        normalized_gateway = payment_gateway

        client = cls._client(
            normalized_gateway,
        )

        cls._require_capability(
            client=client,
            gateway=normalized_gateway,
            operation="refund",
        )

        amount = cls._normalize_amount(
            getattr(
                refund,
                "amount",
                None,
            ),
            operation=cls._OP_REFUND,
        )

        payment_currency = cls._normalize_currency(
            getattr(
                payment,
                "currency",
                None,
            ),
        )

        refund_currency = cls._normalize_currency(
            getattr(
                refund,
                "currency",
                None,
            ),
        )

        if refund_currency != payment_currency:
            raise PaymentCurrencyMismatchError(
                "Refund currency must match the Payment currency.",
                details={
                    "payment_id": getattr(
                        payment,
                        "pk",
                        None,
                    ),
                    "refund_id": getattr(
                        refund,
                        "pk",
                        None,
                    ),
                    "operation": cls._OP_REFUND,
                },
            )

        authority = cls._attempt_authority(
            attempt,
            operation=cls._OP_REFUND,
        )

        order_id = cls._payment_order_id(
            payment,
        )

        refund_reference = cls._refund_reference(
            refund,
        )

        request = GatewayRefundRequest(
            amount=amount,
            authority=authority,
            order_id=order_id,
            currency=refund_currency,
            refund_reference=refund_reference,
        )

        try:
            result = client.refund(
                request,
            )
        except PaymentGatewayNotSupportedError:
            raise
        except PaymentGatewayError:
            raise
        except Exception as exc:
            raise PaymentGatewayError(
                "Payment gateway refund failed.",
                details={
                    "gateway": normalized_gateway.value,
                    "operation": cls._OP_REFUND,
                    "payment_id": getattr(
                        payment,
                        "pk",
                        None,
                    ),
                    "attempt_id": getattr(
                        attempt,
                        "pk",
                        None,
                    ),
                    "refund_id": getattr(
                        refund,
                        "pk",
                        None,
                    ),
                },
                retryable=True,
            ) from exc

        cls._require_result_type(
            result=result,
            expected_type=GatewayRefundResult,
            gateway=normalized_gateway,
            operation=cls._OP_REFUND,
            payment_id=getattr(
                payment,
                "pk",
                None,
            ),
            attempt_id=getattr(
                attempt,
                "pk",
                None,
            ),
            refund_id=getattr(
                refund,
                "pk",
                None,
            ),
        )

        cls._validate_refund_result(
            result=result,
            expected_gateway=normalized_gateway,
            payment=payment,
            refund=refund,
        )

        return result

    # ================================
    # SETTLEMENT
    # ================================

    @classmethod
    def settle(
        cls,
        *,
        amount: Decimal,
        authority: str,
        order_id: str,
        currency: str = Currency.IRR,
        gateway: PaymentGateway | str | None = None,
    ) -> GatewaySettlementResult:
        """
        Execute optional gateway settlement.

        Settlement is a gateway capability, not a Payment domain
        transition.
        """

        normalized_gateway = cls._normalize_gateway(
            gateway,
        )

        client = cls._client(
            normalized_gateway,
        )

        cls._require_capability(
            client=client,
            gateway=normalized_gateway,
            operation="settlement",
        )

        request = GatewaySettlementRequest(
            amount=cls._normalize_amount(
                amount,
                operation=cls._OP_SETTLEMENT,
            ),
            authority=cls._normalize_required_string(
                authority,
                field_name="Payment authority",
                details={
                    "gateway": normalized_gateway.value,
                    "operation": cls._OP_SETTLEMENT,
                },
            ),
            order_id=cls._normalize_required_string(
                order_id,
                field_name="Order ID",
                details={
                    "gateway": normalized_gateway.value,
                    "operation": cls._OP_SETTLEMENT,
                },
            ),
            currency=cls._normalize_currency(
                currency,
            ),
        )

        try:
            result = client.settle_payment(
                request,
            )
        except PaymentGatewayNotSupportedError:
            raise
        except PaymentGatewayError:
            raise
        except Exception as exc:
            raise PaymentGatewayError(
                "Payment gateway settlement failed.",
                details={
                    "gateway": normalized_gateway.value,
                    "operation": cls._OP_SETTLEMENT,
                },
                retryable=True,
            ) from exc

        cls._require_result_type(
            result=result,
            expected_type=GatewaySettlementResult,
            gateway=normalized_gateway,
            operation=cls._OP_SETTLEMENT,
        )

        cls._validate_generic_result_gateway(
            result=result,
            expected_gateway=normalized_gateway,
            operation=cls._OP_SETTLEMENT,
        )

        return result

    # ================================
    # REVERSAL
    # ================================

    @classmethod
    def reverse(
        cls,
        *,
        amount: Decimal,
        authority: str,
        order_id: str,
        currency: str = Currency.IRR,
        gateway: PaymentGateway | str | None = None,
    ) -> GatewayReverseResult:
        """
        Execute optional gateway reversal.
        """

        normalized_gateway = cls._normalize_gateway(
            gateway,
        )

        client = cls._client(
            normalized_gateway,
        )

        cls._require_capability(
            client=client,
            gateway=normalized_gateway,
            operation="reverse",
        )

        request = GatewayReverseRequest(
            amount=cls._normalize_amount(
                amount,
                operation=cls._OP_REVERSE,
            ),
            authority=cls._normalize_required_string(
                authority,
                field_name="Payment authority",
                details={
                    "gateway": normalized_gateway.value,
                    "operation": cls._OP_REVERSE,
                },
            ),
            order_id=cls._normalize_required_string(
                order_id,
                field_name="Order ID",
                details={
                    "gateway": normalized_gateway.value,
                    "operation": cls._OP_REVERSE,
                },
            ),
            currency=cls._normalize_currency(
                currency,
            ),
        )

        try:
            result = client.reverse_payment(
                request,
            )
        except PaymentGatewayNotSupportedError:
            raise
        except PaymentGatewayError:
            raise
        except Exception as exc:
            raise PaymentGatewayError(
                "Payment gateway reversal failed.",
                details={
                    "gateway": normalized_gateway.value,
                    "operation": cls._OP_REVERSE,
                },
                retryable=True,
            ) from exc

        cls._require_result_type(
            result=result,
            expected_type=GatewayReverseResult,
            gateway=normalized_gateway,
            operation=cls._OP_REVERSE,
        )

        cls._validate_generic_result_gateway(
            result=result,
            expected_gateway=normalized_gateway,
            operation=cls._OP_REVERSE,
        )

        return result

    # ================================
    # INQUIRY
    # ================================

    @classmethod
    def inquire(
        cls,
        *,
        authority: str,
        order_id: str,
        amount: Decimal | None = None,
        currency: str = Currency.IRR,
        gateway: PaymentGateway | str | None = None,
    ) -> GatewayInquiryResult:
        """
        Query current/known gateway transaction state.

        Inquiry is deliberately separate from verification.
        """

        normalized_gateway = cls._normalize_gateway(
            gateway,
        )

        client = cls._client(
            normalized_gateway,
        )

        cls._require_capability(
            client=client,
            gateway=normalized_gateway,
            operation="inquiry",
        )

        normalized_amount = (
            None
            if amount is None
            else cls._normalize_amount(
                amount,
                operation=cls._OP_INQUIRY,
            )
        )

        request = GatewayInquiryRequest(
            authority=cls._normalize_required_string(
                authority,
                field_name="Payment authority",
                details={
                    "gateway": normalized_gateway.value,
                    "operation": cls._OP_INQUIRY,
                },
            ),
            order_id=cls._normalize_required_string(
                order_id,
                field_name="Order ID",
                details={
                    "gateway": normalized_gateway.value,
                    "operation": cls._OP_INQUIRY,
                },
            ),
            amount=normalized_amount,
            currency=cls._normalize_currency(
                currency,
            ),
        )

        try:
            result = client.inquire_payment(
                request,
            )
        except PaymentGatewayNotSupportedError:
            raise
        except PaymentGatewayError:
            raise
        except Exception as exc:
            raise PaymentGatewayError(
                "Payment gateway inquiry failed.",
                details={
                    "gateway": normalized_gateway.value,
                    "operation": cls._OP_INQUIRY,
                },
                retryable=True,
            ) from exc

        cls._require_result_type(
            result=result,
            expected_type=GatewayInquiryResult,
            gateway=normalized_gateway,
            operation=cls._OP_INQUIRY,
        )

        cls._validate_generic_result_gateway(
            result=result,
            expected_gateway=normalized_gateway,
            operation=cls._OP_INQUIRY,
        )

        return result

    # ================================
    # CALLBACK
    # ================================

    @classmethod
    def parse_callback(
        cls,
        *,
        payload: Mapping[str, Any],
        gateway: PaymentGateway | str,
    ) -> GatewayCallback:
        """
        Parse a provider callback.

        IMPORTANT:

        This method ONLY normalizes provider input.

        It does NOT:

            - identify Payment
            - identify PaymentAttempt
            - lock anything
            - verify amount
            - mutate state
            - persist callback
            - consume Payment
            - publish events

        The callback/application service performs those operations.

        Treat callback data as untrusted evidence.
        """

        normalized_gateway = cls._normalize_gateway(
            gateway,
        )

        if not isinstance(
            payload,
            Mapping,
        ):
            raise PaymentGatewayError(
                "Gateway callback payload must be a mapping.",
                details={
                    "gateway": normalized_gateway.value,
                    "operation": cls._OP_CALLBACK,
                },
                retryable=False,
            )

        client = cls._client(
            normalized_gateway,
        )

        cls._require_capability(
            client=client,
            gateway=normalized_gateway,
            operation="callback",
        )

        try:
            result = client.parse_callback(
                payload,
            )
        except PaymentGatewayNotSupportedError:
            raise
        except PaymentGatewayError:
            raise
        except Exception as exc:
            raise PaymentGatewayError(
                "Failed to parse payment gateway callback.",
                details={
                    "gateway": normalized_gateway.value,
                    "operation": cls._OP_CALLBACK,
                },
                retryable=False,
            ) from exc

        cls._require_result_type(
            result=result,
            expected_type=GatewayCallback,
            gateway=normalized_gateway,
            operation=cls._OP_CALLBACK,
        )

        cls._validate_callback_result(
            result=result,
            expected_gateway=normalized_gateway,
        )

        return result

    # ================================
    # PAYMENT / ATTEMPT VALIDATION
    # ================================

    @classmethod
    def _validate_payment_attempt_pair(
        cls,
        *,
        payment: Any,
        attempt: Any,
    ) -> None:
        """
        Ensure that PaymentAttempt belongs to Payment.

        This is an object consistency check.

        It does NOT provide concurrency protection.

        The application service remains responsible for locking.
        """

        if payment is None:
            raise PaymentGatewayError(
                "Payment is required for gateway operation.",
                details={
                    "operation": "payment_attempt_validation",
                },
                retryable=False,
            )

        if attempt is None:
            raise PaymentGatewayError(
                "Payment attempt is required for gateway operation.",
                details={
                    "operation": "payment_attempt_validation",
                },
                retryable=False,
            )

        payment_id = getattr(
            payment,
            "pk",
            None,
        )

        attempt_payment_id = getattr(
            attempt,
            "payment_id",
            None,
        )

        if (
            payment_id is None
            or attempt_payment_id is None
            or payment_id != attempt_payment_id
        ):
            raise PaymentGatewayError(
                "PaymentAttempt does not belong to Payment.",
                details={
                    "payment_id": payment_id,
                    "attempt_id": getattr(
                        attempt,
                        "pk",
                        None,
                    ),
                    "attempt_payment_id": attempt_payment_id,
                    "operation": "payment_attempt_validation",
                },
                retryable=False,
            )

    # ================================
    # PAYMENT GATEWAY SNAPSHOT
    # ================================

    @classmethod
    def _payment_gateway(
        cls,
        payment: Any,
    ) -> PaymentGateway:
        """
        Resolve the immutable gateway snapshot stored on Payment.

        Payment.gateway is authoritative for historical operations.

        DEFAULT_PAYMENT_GATEWAY is NEVER used for an existing Payment.
        """

        gateway = getattr(
            payment,
            "gateway",
            None,
        )

        if gateway is None:
            raise PaymentGatewayNotSupportedError(
                "Payment does not specify a gateway.",
                details={
                    "payment_id": getattr(
                        payment,
                        "pk",
                        None,
                    ),
                },
            )

        return cls._normalize_gateway(
            gateway,
        )

    # ================================
    # PAYMENT ATTEMPT IDENTITY
    # ================================

    @staticmethod
    def _attempt_authority(
        attempt: Any,
        *,
        operation: str,
    ) -> str:
        """
        Resolve the historical gateway authority from PaymentAttempt.

        This is the authoritative location of gateway execution
        identity.
        """

        authority = getattr(
            attempt,
            "authority_id",
            None,
        )

        return GatewayService._normalize_required_string(
            authority,
            field_name="Payment attempt authority",
            details={
                "operation": operation,
                "attempt_id": getattr(
                    attempt,
                    "pk",
                    None,
                ),
            },
        )

    # ================================
    # PAYMENT ORDER ID
    # ================================

    @staticmethod
    def _payment_order_id(
        payment: Any,
    ) -> str:
        """
        Resolve stable Order identifier.

        The Order object is read only.

        No query is performed here.
        """

        order_id = getattr(
            payment,
            "order_id",
            None,
        )

        if order_id is None:
            order = getattr(
                payment,
                "order",
                None,
            )

            order_id = getattr(
                order,
                "pk",
                None,
            )

        return GatewayService._normalize_required_string(
            order_id,
            field_name="Order ID",
            details={
                "payment_id": getattr(
                    payment,
                    "pk",
                    None,
                ),
                "operation": "order_identity",
            },
        )

    # ================================
    # REFUND REFERENCE
    # ================================

    @staticmethod
    def _refund_reference(
        refund: Any,
    ) -> str | None:
        """
        Return the internal Refund identifier as provider-neutral
        correlation/reference data.

        Provider-specific refund identities must be generated by the
        provider implementation.
        """

        value = getattr(
            refund,
            "pk",
            None,
        )

        if value is None:
            return None

        return str(value)

    # ================================
    # FINANCIAL NORMALIZATION
    # ================================

    @staticmethod
    def _normalize_amount(
        amount: Decimal | Any,
        *,
        operation: str,
    ) -> Decimal:
        """
        Normalize a financial amount without floating-point arithmetic.

        Rules:

            amount must be finite
            amount must be > 0

        Currency conversion is deliberately outside GatewayService.
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
            raise PaymentGatewayError(
                "Invalid financial amount for gateway operation.",
                details={
                    "operation": operation,
                },
                retryable=False,
            ) from exc

        if not normalized.is_finite():
            raise PaymentGatewayError(
                "Financial amount must be finite.",
                details={
                    "operation": operation,
                },
                retryable=False,
            )

        if normalized <= Decimal("0"):
            raise PaymentGatewayError(
                "Gateway amount must be greater than zero.",
                details={
                    "operation": operation,
                },
                retryable=False,
            )

        return normalized

    @staticmethod
    def _normalize_currency(
        currency: str | None,
    ) -> str:
        """
        Normalize currency identifier.

        No FX or currency conversion is performed.
        """

        normalized = str(
            currency or "",
        ).strip()

        if not normalized:
            raise PaymentGatewayError(
                "Payment currency is required.",
                details={
                    "operation": "currency_validation",
                },
                retryable=False,
            )

        return normalized

    # ================================
    # STRING NORMALIZATION
    # ================================

    @staticmethod
    def _normalize_required_string(
        value: Any,
        *,
        field_name: str,
        details: Mapping[str, Any] | None = None,
    ) -> str:
        """
        Normalize a required textual field.

        No sensitive values are copied into exception details.
        """

        normalized = str(
            value or "",
        ).strip()

        if not normalized:
            error_details = dict(
                details or {},
            )

            error_details["field"] = field_name

            raise PaymentGatewayError(
                f"{field_name} is required.",
                details=error_details,
                retryable=False,
            )

        return normalized

    # ================================
    # RESULT TYPE VALIDATION
    # ================================

    @staticmethod
    def _require_result_type(
        *,
        result: Any,
        expected_type: type,
        gateway: PaymentGateway,
        operation: str,
        **details: Any,
    ) -> None:
        """
        Enforce typed provider result contract.
        """

        if isinstance(
            result,
            expected_type,
        ):
            return

        error_details = {
            "gateway": gateway.value,
            "operation": operation,
            **details,
        }

        raise PaymentGatewayError(
            "Gateway returned an invalid result.",
            details=error_details,
            retryable=False,
        )

    # ================================
    # RESULT GATEWAY VALIDATION
    # ================================

    @staticmethod
    def _validate_generic_result_gateway(
        *,
        result: Any,
        expected_gateway: PaymentGateway,
        operation: str,
    ) -> None:
        """
        Ensure provider result identifies the gateway that was actually
        called.

        A provider must never be allowed to return evidence belonging
        to another gateway.
        """

        result_gateway = getattr(
            result,
            "gateway",
            None,
        )

        if result_gateway is None:
            raise PaymentGatewayError(
                "Gateway result does not contain gateway identity.",
                details={
                    "gateway": expected_gateway.value,
                    "operation": operation,
                },
                retryable=False,
            )

        try:
            normalized_result_gateway = GatewayService._normalize_gateway(
                result_gateway,
            )
        except PaymentGatewayError as exc:
            raise PaymentGatewayError(
                "Gateway returned an invalid gateway identity.",
                details={
                    "gateway": expected_gateway.value,
                    "operation": operation,
                },
                retryable=False,
            ) from exc

        if normalized_result_gateway != expected_gateway:
            raise PaymentGatewayMismatchError(
                "Gateway result does not match the selected gateway.",
                details={
                    "expected_gateway": expected_gateway.value,
                    "result_gateway": normalized_result_gateway.value,
                    "operation": operation,
                },
            )

    # ================================
    # PAYMENT RESULT VALIDATION
    # ================================

    @classmethod
    def _validate_payment_result(
        cls,
        *,
        result: GatewayPaymentResult,
        expected_gateway: PaymentGateway,
        operation: str,
    ) -> None:
        """
        Validate payment initiation evidence.

        A successful initiation must provide an authority because
        subsequent payment URL / verification operations require it.
        """

        cls._validate_generic_result_gateway(
            result=result,
            expected_gateway=expected_gateway,
            operation=operation,
        )

        if not result.success:
            return

        authority = str(
            result.authority or "",
        ).strip()

        if not authority:
            raise PaymentGatewayError(
                "Successful gateway payment initiation requires an authority.",
                details={
                    "gateway": expected_gateway.value,
                    "operation": operation,
                },
                retryable=False,
            )

    # ================================
    # VERIFICATION RESULT VALIDATION
    # ================================

    @classmethod
    def _validate_verification_result(
        cls,
        *,
        result: GatewayVerificationResult,
        payment: Any,
        attempt: Any,
        expected_gateway: PaymentGateway,
    ) -> None:
        """
        Validate normalized verification evidence against immutable
        Payment financial snapshots and historical Attempt identity.

        This is evidence validation only.

        It does NOT mutate Payment.
        """

        cls._validate_generic_result_gateway(
            result=result,
            expected_gateway=expected_gateway,
            operation=cls._OP_VERIFY,
        )

        expected_amount = cls._normalize_amount(
            getattr(
                payment,
                "amount",
                None,
            ),
            operation=cls._OP_VERIFY,
        )

        expected_currency = cls._normalize_currency(
            getattr(
                payment,
                "currency",
                None,
            ),
        )

        expected_authority = cls._attempt_authority(
            attempt,
            operation=cls._OP_VERIFY,
        )

        # ------------------------------------------------------------
        # If gateway reports amount, it becomes evidence that MUST
        # match the immutable Payment snapshot.
        # ------------------------------------------------------------

        if result.amount is not None:
            gateway_amount = cls._normalize_amount(
                result.amount,
                operation=cls._OP_VERIFY,
            )

            if gateway_amount != expected_amount:
                raise PaymentAmountMismatchError(
                    "Gateway verification amount does not match Payment amount.",
                    payment_id=getattr(
                        payment,
                        "pk",
                        None,
                    ),
                    details={
                        "operation": cls._OP_VERIFY,
                        "attempt_id": getattr(
                            attempt,
                            "pk",
                            None,
                        ),
                    },
                )

        # ------------------------------------------------------------
        # If gateway reports currency, it MUST match Payment currency.
        # ------------------------------------------------------------

        if result.currency is not None:
            gateway_currency = cls._normalize_currency(
                result.currency,
            )

            if gateway_currency != expected_currency:
                raise PaymentCurrencyMismatchError(
                    "Gateway verification currency does not match Payment currency.",
                    details={
                        "payment_id": getattr(
                            payment,
                            "pk",
                            None,
                        ),
                        "attempt_id": getattr(
                            attempt,
                            "pk",
                            None,
                        ),
                        "operation": cls._OP_VERIFY,
                    },
                )

        # ------------------------------------------------------------
        # Successful verification must contain gateway financial
        # identity.
        # ------------------------------------------------------------

        if result.success:
            if not (
                str(
                    result.gateway_reference or "",
                ).strip()
                or str(
                    result.gateway_transaction_id or "",
                ).strip()
            ):
                raise PaymentGatewayError(
                    "Successful gateway verification requires gateway identity.",
                    details={
                        "gateway": expected_gateway.value,
                        "payment_id": getattr(
                            payment,
                            "pk",
                            None,
                        ),
                        "attempt_id": getattr(
                            attempt,
                            "pk",
                            None,
                        ),
                        "operation": cls._OP_VERIFY,
                    },
                    retryable=False,
                )

            # The request authority is the historical attempt authority.
            #
            # GatewayVerificationResult does not currently expose an
            # authority field, therefore the actual authority correlation
            # remains the responsibility of the application verification
            # workflow / gateway implementation.
            #
            # We intentionally do NOT invent or mutate authority here.

            if not expected_authority:
                raise PaymentGatewayError(
                    "PaymentAttempt authority is required for verification.",
                    details={
                        "gateway": expected_gateway.value,
                        "payment_id": getattr(
                            payment,
                            "pk",
                            None,
                        ),
                        "attempt_id": getattr(
                            attempt,
                            "pk",
                            None,
                        ),
                        "operation": cls._OP_VERIFY,
                    },
                    retryable=False,
                )

    # ================================
    # REFUND RESULT VALIDATION
    # ================================

    @classmethod
    def _validate_refund_result(
        cls,
        *,
        result: GatewayRefundResult,
        expected_gateway: PaymentGateway,
        payment: Any,
        refund: Any,
    ) -> None:
        """
        Validate normalized refund evidence.

        GatewayService does NOT calculate refundable balance.

        It only verifies:

            provider identity
            gateway identity
            currency consistency
            successful refund identity
        """

        cls._validate_generic_result_gateway(
            result=result,
            expected_gateway=expected_gateway,
            operation=cls._OP_REFUND,
        )

        payment_currency = cls._normalize_currency(
            getattr(
                payment,
                "currency",
                None,
            ),
        )

        refund_currency = cls._normalize_currency(
            getattr(
                refund,
                "currency",
                None,
            ),
        )

        if refund_currency != payment_currency:
            raise PaymentCurrencyMismatchError(
                "Refund currency does not match Payment currency.",
                details={
                    "payment_id": getattr(
                        payment,
                        "pk",
                        None,
                    ),
                    "refund_id": getattr(
                        refund,
                        "pk",
                        None,
                    ),
                    "operation": cls._OP_REFUND,
                },
            )

        if not result.success:
            return

        if not (
            str(
                result.gateway_reference or "",
            ).strip()
            or str(
                result.gateway_transaction_id or "",
            ).strip()
        ):
            raise PaymentGatewayError(
                "Successful gateway refund requires gateway identity.",
                details={
                    "gateway": expected_gateway.value,
                    "payment_id": getattr(
                        payment,
                        "pk",
                        None,
                    ),
                    "refund_id": getattr(
                        refund,
                        "pk",
                        None,
                    ),
                    "operation": cls._OP_REFUND,
                },
                retryable=False,
            )

    # ================================
    # CALLBACK RESULT VALIDATION
    # ================================

    @classmethod
    def _validate_callback_result(
        cls,
        *,
        result: GatewayCallback,
        expected_gateway: PaymentGateway,
    ) -> None:
        """
        Validate normalized callback envelope.

        Callback data remains untrusted until the application service
        correlates it with Payment/Attempt and performs verification.
        """

        cls._validate_generic_result_gateway(
            result=result,
            expected_gateway=expected_gateway,
            operation=cls._OP_CALLBACK,
        )

        # A successful callback should normally carry at least one
        # stable gateway identity.
        #
        # We intentionally do not require success=True here because
        # failed callbacks may legitimately contain no financial
        # reference depending on provider behavior.

        if result.success:
            has_identity = bool(
                str(
                    result.authority or "",
                ).strip()
                or str(
                    result.gateway_reference or "",
                ).strip()
                or str(
                    result.gateway_transaction_id or "",
                ).strip()
            )

            if not has_identity:
                raise PaymentGatewayError(
                    "Successful gateway callback requires gateway identity.",
                    details={
                        "gateway": expected_gateway.value,
                        "operation": cls._OP_CALLBACK,
                    },
                    retryable=False,
                )

    # ================================
    # HISTORICAL ATTEMPT HELPERS
    # ================================

    @staticmethod
    def _attempt_is_successful(
        attempt: Any,
    ) -> bool:
        """
        Small pure helper for callers/tests.

        This method does not authorize refund.

        Refund application policy remains outside GatewayService.
        """

        status = getattr(
            attempt,
            "status",
            None,
        )

        return status == PaymentAttemptStatus.SUCCESS