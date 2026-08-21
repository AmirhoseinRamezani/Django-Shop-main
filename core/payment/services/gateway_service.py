# core/payment/services/gateway_service.py
from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from django.conf import settings

from payment.enums import Currency, PaymentGateway
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
    Single provider-independent facade for external payment gateways.

    ------------------------------------
    ARCHITECTURAL BOUNDARY
    ------------------------------------

        Application Service
                |
                v
        GatewayService
                |
                v
        GatewayRegistry
                |
                v
        Concrete Gateway Adapter
                |
                v
        External Provider

    ------------------------------------
    RESPONSIBILITIES
    ------------------------------------

    GatewayService owns:

    - gateway normalization
    - gateway resolution
    - gateway client construction
    - request DTO construction
    - provider invocation
    - capability checks
    - provider exception normalization
    - typed result validation
    - financial evidence validation
    - gateway identity validation
    - callback normalization

    ------------------------------------
    EXPLICIT NON-RESPONSIBILITIES
    ------------------------------------

    GatewayService MUST NOT:

    - access ORM
    - open database transactions
    - use repositories
    - use select_for_update()
    - mutate Payment
    - mutate PaymentAttempt
    - mutate Refund
    - mutate Order
    - authorize refunds
    - calculate refundable balance
    - publish events
    - create outbox records
    - persist idempotency keys
    - schedule retries
    - perform reconciliation
    - perform business authorization
    - mutate financial state

    ------------------------------------
    PAYMENT / ATTEMPT BOUNDARY
    ------------------------------------

    Payment owns:

        amount
        currency
        order
        historical gateway selection

    PaymentAttempt owns:

        authority_id
        gateway_reference
        gateway_transaction_id

    Therefore:

        Payment.gateway
            = historical provider selection

        PaymentAttempt.authority_id
            = execution identity

    GatewayService MUST NEVER read:

        payment.authority_id

    for verify/refund.

    ------------------------------------
    RESULT CONTRACT
    ------------------------------------

    Concrete gateway adapters MUST return normalized DTOs defined by
    payment.providers.base.

    Provider-specific dictionaries/payloads MUST NOT cross this boundary.

    GatewayService rejects malformed provider results before returning
    them to application services.
    """

    # ================================
    # OPERATIONS
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

        This is only valid before a Payment has acquired a historical
        gateway snapshot.

        Existing Payments MUST use Payment.gateway.
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

        None means DEFAULT_PAYMENT_GATEWAY.

        Existing historical Payment operations must explicitly provide
        their stored gateway through Payment.gateway.
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
            return PaymentGateway(
                str(gateway).strip(),
            )
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
        Return whether a concrete gateway implementation is registered.

        This does not represent operational health.
        """

        try:
            normalized = cls._normalize_gateway(gateway)
            return GatewayRegistry.is_registered(normalized)
        except PaymentGatewayError:
            return False

    @classmethod
    def registered_gateways(
        cls,
    ) -> tuple[PaymentGateway, ...]:
        """
        Return all registered gateway identifiers.
        """

        return GatewayRegistry.gateways()

    @classmethod
    def _client(
        cls,
        gateway: PaymentGateway | str | None,
    ) -> Any:
        """
        Resolve and instantiate a concrete gateway adapter.

        No database access.
        No persistence.
        """

        normalized = cls._normalize_gateway(gateway)

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
            return client_class()
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

    @classmethod
    def _require_capability(
        cls,
        *,
        client: Any,
        gateway: PaymentGateway,
        operation: str,
    ) -> None:
        """
        Require an adapter capability before invoking it.

        Particularly important for refund so that an unsupported
        operation can never be interpreted as a financial success.
        """

        try:
            supported = bool(
                client.supports(operation),
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
        Initiate a payment at the external gateway.

        This method does NOT create or mutate Payment/PaymentAttempt.

        The application workflow owns:

            Payment creation
                ->
            Attempt creation
                ->
            gateway initiation
                ->
            Attempt identity persistence
        """

        normalized_gateway = cls._normalize_gateway(gateway)
        client = cls._client(normalized_gateway)

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
        Build the user-facing payment URL.

        No database access.
        No state mutation.
        """

        normalized_gateway = cls._normalize_gateway(gateway)

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

        if not isinstance(result, str):
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
        Verify a Payment through its authoritative PaymentAttempt.

        IMPORTANT:

            payment.gateway
                -> selects historical provider

            attempt.authority_id
                -> selects gateway execution identity

        NEVER read:

            payment.authority_id

        This method performs external I/O only.

        It does not:

            - open transactions
            - lock rows
            - mutate Payment
            - mutate PaymentAttempt
            - persist verification
        """

        cls._validate_payment_attempt_pair(
            payment=payment,
            attempt=attempt,
        )

        gateway = cls._payment_gateway(
            payment,
        )

        client = cls._client(
            gateway,
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
                    "gateway": gateway.value,
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
            gateway=gateway,
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
            expected_gateway=gateway,
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
        Execute a gateway refund.

        GatewayService only performs gateway communication and evidence
        validation.

        It does NOT authorize the refund amount.

        Refund authorization belongs to the application refund workflow
        while Payment is locked.

        Authority source:

            PaymentAttempt.authority_id

        Historical gateway source:

            Payment.gateway
        """

        cls._validate_payment_attempt_pair(
            payment=payment,
            attempt=attempt,
        )

        payment_gateway = cls._payment_gateway(
            payment,
        )

        # ------------------------------------------------------------
        # Optional explicit gateway is only a consistency assertion.
        # It must never override historical Payment.gateway.
        # ------------------------------------------------------------

        if gateway is not None:
            requested_gateway = cls._normalize_gateway(
                gateway,
            )

            if requested_gateway != payment_gateway:
                raise PaymentGatewayMismatchError(
                    "Refund gateway does not match the historical "
                    "Payment gateway.",
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

        client = cls._client(
            payment_gateway,
        )

        # ------------------------------------------------------------
        # CRITICAL:
        #
        # Check refund support BEFORE creating request / calling
        # provider.
        # ------------------------------------------------------------

        cls._require_capability(
            client=client,
            gateway=payment_gateway,
            operation=cls._OP_REFUND,
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
                "Refund currency must match Payment currency.",
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
                    "gateway": payment_gateway.value,
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
            gateway=payment_gateway,
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
            expected_gateway=payment_gateway,
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
        Execute an optional gateway settlement operation.

        Settlement is a provider capability.

        It is NOT a Payment state transition.
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
            operation=cls._OP_SETTLEMENT,
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
        Execute an optional gateway reversal.
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
            operation=cls._OP_REVERSE,
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
        Query gateway transaction state.

        Inquiry is evidence retrieval only.
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
            operation=cls._OP_INQUIRY,
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
    # CALLBACK NORMALIZATION
    # ================================

    @classmethod
    def parse_callback(
        cls,
        *,
        payload: Mapping[str, Any],
        gateway: PaymentGateway | str,
    ) -> GatewayCallback:
        """
        Normalize an untrusted provider callback.

        IMPORTANT:

        This method does not:

        - identify Payment
        - identify PaymentAttempt
        - lock rows
        - verify amount against Payment
        - mutate state
        - persist anything
        - consume Payment
        - publish events

        It only converts provider input into the normalized callback DTO.

        The application verification workflow remains responsible for
        financial verification.
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
            operation=cls._OP_CALLBACK,
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
    # PAYMENT / ATTEMPT CONSISTENCY
    # ================================

    @classmethod
    def _validate_payment_attempt_pair(
        cls,
        *,
        payment: Any,
        attempt: Any,
    ) -> None:
        """
        Ensure that the supplied attempt belongs to the supplied Payment.

        This is a consistency check only.

        It is NOT a concurrency primitive.

        Locking remains owned by the application service.
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
    # HISTORICAL PAYMENT GATEWAY
    # ================================

    @classmethod
    def _payment_gateway(
        cls,
        payment: Any,
    ) -> PaymentGateway:
        """
        Resolve the historical gateway stored on Payment.

        DEFAULT_PAYMENT_GATEWAY is never used for an existing Payment.
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
    # PAYMENT ATTEMPT AUTHORITY
    # ================================

    @staticmethod
    def _attempt_authority(
        attempt: Any,
        *,
        operation: str,
    ) -> str:
        """
        Resolve gateway authority exclusively from PaymentAttempt.
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
    # ORDER ID
    # ================================

    @staticmethod
    def _payment_order_id(
        payment: Any,
    ) -> str:
        """
        Resolve the stable Order identifier.

        No database query is performed.
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
        Return an internal Refund identifier as provider-neutral
        correlation data.

        Provider-specific refund identities are generated by adapters.
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
    # AMOUNT NORMALIZATION
    # ================================

    @staticmethod
    def _normalize_amount(
        amount: Decimal | Any,
        *,
        operation: str,
    ) -> Decimal:
        """
        Normalize a financial amount without floating-point arithmetic.

        Requirements:

        - finite
        - strictly positive
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

    # ================================
    # CURRENCY NORMALIZATION
    # ================================

    @staticmethod
    def _normalize_currency(
        currency: str | None,
    ) -> str:
        """
        Normalize a currency identifier.

        No FX conversion is performed.
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
        Normalize and require a textual value.
        Sensitive provider data must never be placed in exception details.
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
        Enforce the typed gateway result contract.

        Provider dictionaries are rejected here.
        """

        if isinstance(
            result,
            expected_type,
        ):
            return

        raise PaymentGatewayError(
            "Gateway returned an invalid result.",
            details={
                "gateway": gateway.value,
                "operation": operation,
                **details,
            },
            retryable=False,
        )

    # ================================
    # GENERIC RESULT GATEWAY VALIDATION
    # ================================

    @staticmethod
    def _validate_generic_result_gateway(
        *,
        result: Any,
        expected_gateway: PaymentGateway,
        operation: str,
    ) -> None:
        """
        Ensure returned evidence belongs to the gateway actually called.
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
            normalized_result_gateway = (
                GatewayService._normalize_gateway(
                    result_gateway,
                )
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
    ) -> None:
        """
        Validate payment initiation evidence.
        """

        cls._validate_generic_result_gateway(
            result=result,
            expected_gateway=expected_gateway,
            operation=cls._OP_INITIATE,
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
                    "operation": cls._OP_INITIATE,
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
        Validate normalized verification evidence.

        This method never changes financial state.
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
        # Amount evidence
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
        # Currency evidence
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
        # Successful verification MUST have gateway identity.
        # ------------------------------------------------------------

        if result.success:
            has_identity = bool(
                str(
                    result.gateway_reference or "",
                ).strip()
                or str(
                    result.gateway_transaction_id or "",
                ).strip()
            )

            if not has_identity:
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

            # --------------------------------------------------------
            # Authority is already required from PaymentAttempt.
            #
            # GatewayService intentionally does not mutate it.
            # --------------------------------------------------------

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

        It validates only:

        - provider identity
        - gateway identity
        - currency consistency
        - successful refund identity
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

        # ------------------------------------------------------------
        # Provider explicitly rejected the refund.
        #
        # Application service decides the domain state.
        # ------------------------------------------------------------

        if not result.success:
            return

        # ------------------------------------------------------------
        # CRITICAL:
        #
        # A successful refund without provider identity is never
        # accepted as financial evidence.
        # ------------------------------------------------------------

        has_identity = bool(
            str(
                result.gateway_reference or "",
            ).strip()
            or str(
                result.gateway_transaction_id or "",
            ).strip()
        )

        if not has_identity:
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
        Validate normalized callback evidence.

        Callback remains untrusted until application-level verification.

        No state transition occurs here.
        """

        cls._validate_generic_result_gateway(
            result=result,
            expected_gateway=expected_gateway,
            operation=cls._OP_CALLBACK,
        )

        if not result.success:
            return

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
    # ATTEMPT HELPERS
    # ================================

    @staticmethod
    def _attempt_is_successful(
        attempt: Any,
    ) -> bool:
        """
        Pure compatibility helper.

        This does not authorize refunds.
        """

        status = getattr(
            attempt,
            "status",
            None,
        )

        try:
            from payment.enums import PaymentAttemptStatus

            return status == PaymentAttemptStatus.SUCCESS
        except ImportError:
            return False