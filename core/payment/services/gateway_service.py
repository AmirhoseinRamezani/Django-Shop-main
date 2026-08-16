# core/payment/services/gateway_service.py

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from django.conf import settings

from payment.enums import Currency, PaymentGateway
from payment.exceptions import (
    PaymentGatewayError,
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

    Responsibilities:
        - gateway normalization
        - gateway resolution
        - provider client construction
        - request construction
        - provider operation execution
        - normalized result validation
        - infrastructure error normalization

    Non-responsibilities:
        - database access
        - transactions
        - repository persistence
        - Payment state transitions
        - Refund state transitions
        - refund authorization
        - business policies
        - gateway log persistence
        - event publication
        - provider-specific parsing
    """

    # ================================================================
    # GATEWAY RESOLUTION
    # ================================================================

    @classmethod
    def current_gateway(cls) -> PaymentGateway:
        """
        Return the configured default gateway.

        This is used only when an operation has no historical gateway
        snapshot.
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

        None means the configured default gateway.
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
            return PaymentGateway(str(gateway))
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
        """

        try:
            normalized = cls._normalize_gateway(gateway)
        except PaymentGatewayError:
            return False

        return GatewayRegistry.is_registered(
            normalized,
        )

    @classmethod
    def registered_gateways(
        cls,
    ) -> tuple[PaymentGateway, ...]:
        """
        Return currently registered gateway identifiers.
        """

        return GatewayRegistry.gateways()

    @classmethod
    def _client(
        cls,
        gateway: PaymentGateway | str | None = None,
    ) -> Any:
        """
        Resolve and instantiate a concrete gateway client.
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
                },
                retryable=False,
            ) from exc

        return client

    # ================================================================
    # PAYMENT INITIATION
    # ================================================================

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
        Initiate a payment.

        Gateway selection is explicit when supplied; otherwise the
        configured default gateway is used.
        """

        normalized_gateway = cls._normalize_gateway(
            gateway,
        )

        client = cls._client(
            normalized_gateway,
        )

        request = GatewayPaymentRequest(
            amount=cls._normalize_amount(
                amount,
            ),
            order_id=str(order_id),
            callback_url=str(callback_url),
            currency=cls._normalize_currency(
                currency,
            ),
            description=str(
                description or "",
            ),
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
                    "operation": "initiate_payment",
                },
                retryable=True,
            ) from exc

        cls._require_result_type(
            result=result,
            expected_type=GatewayPaymentResult,
            gateway=normalized_gateway,
            operation="initiate_payment",
        )

        return result

    # ================================================================
    # PAYMENT URL
    # ================================================================

    @classmethod
    def payment_url(
        cls,
        authority: str,
        *,
        gateway: PaymentGateway | str | None = None,
    ) -> str:
        """
        Build the user-facing gateway payment URL.
        """

        normalized_gateway = cls._normalize_gateway(
            gateway,
        )

        client = cls._client(
            normalized_gateway,
        )

        normalized_authority = cls._normalize_required_string(
            authority,
            field_name="Payment authority",
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
                    "operation": "payment_url",
                },
                retryable=False,
            ) from exc

        if not isinstance(result, str) or not result.strip():
            raise PaymentGatewayError(
                "Gateway returned an invalid payment URL.",
                details={
                    "gateway": normalized_gateway.value,
                    "operation": "payment_url",
                },
                retryable=False,
            )

        return result.strip()

    # ================================================================
    # PAYMENT VERIFICATION
    # ================================================================

    @classmethod
    def verify(
        cls,
        payment: Any,
    ) -> GatewayVerificationResult:
        """
        Verify an existing Payment.

        Payment.gateway is authoritative.
        DEFAULT_PAYMENT_GATEWAY is never used for historical payments.
        """

        normalized_gateway = cls._payment_gateway(
            payment,
        )

        client = cls._client(
            normalized_gateway,
        )

        amount = cls._normalize_amount(
            payment.amount,
        )

        authority = cls._normalize_required_string(
            getattr(
                payment,
                "authority_id",
                "",
            ),
            field_name="Payment authority",
            details={
                "gateway": normalized_gateway.value,
                "operation": "verify",
                "payment_id": getattr(
                    payment,
                    "pk",
                    None,
                ),
            },
        )

        order_id = cls._payment_order_id(
            payment,
        )

        request = GatewayVerificationRequest(
            amount=amount,
            authority=authority,
            order_id=order_id,
            currency=cls._normalize_currency(
                getattr(
                    payment,
                    "currency",
                    Currency.IRR,
                ),
            ),
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
                    "operation": "verify",
                    "payment_id": getattr(
                        payment,
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
            operation="verify",
            payment_id=getattr(
                payment,
                "pk",
                None,
            ),
        )

        return result

    # ================================================================
    # REFUND
    # ================================================================

    @classmethod
    def refund(
        cls,
        *,
        payment: Any,
        refund: Any,
        gateway: PaymentGateway | str | None = None,
    ) -> GatewayRefundResult:
        """
        Execute a refund through the historical Payment gateway.

        For an existing Payment, Payment.gateway is authoritative.
        An explicitly supplied gateway must match that historical
        gateway and can never silently replace it.
        """

        payment_gateway = cls._payment_gateway(
            payment,
        )

        if gateway is not None:
            requested_gateway = cls._normalize_gateway(
                gateway,
            )

            if requested_gateway != payment_gateway:
                raise PaymentGatewayNotSupportedError(
                    "Refund gateway does not match the Payment gateway.",
                    details={
                        "payment_id": getattr(
                            payment,
                            "pk",
                            None,
                        ),
                        "payment_gateway": payment_gateway.value,
                        "requested_gateway": requested_gateway.value,
                        "operation": "refund",
                    },
                )

        normalized_gateway = payment_gateway

        client = cls._client(
            normalized_gateway,
        )

        if not client.supports(
            "refund",
        ):
            raise PaymentGatewayNotSupportedError(
                "Selected payment gateway does not support refunds.",
                details={
                    "gateway": normalized_gateway.value,
                    "operation": "refund",
                },
            )

        amount = cls._normalize_amount(
            refund.amount,
        )

        authority = cls._normalize_required_string(
            getattr(
                payment,
                "authority_id",
                "",
            ),
            field_name="Payment authority",
            details={
                "gateway": normalized_gateway.value,
                "operation": "refund",
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
            },
        )

        order_id = cls._payment_order_id(
            payment,
        )

        refund_currency = cls._normalize_currency(
            getattr(
                refund,
                "currency",
                getattr(
                    payment,
                    "currency",
                    Currency.IRR,
                ),
            ),
        )

        request = GatewayRefundRequest(
            amount=amount,
            authority=authority,
            order_id=order_id,
            currency=refund_currency,
            refund_reference=cls._refund_reference(
                refund,
            ),
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
                    "operation": "refund",
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
                },
                retryable=True,
            ) from exc

        cls._require_result_type(
            result=result,
            expected_type=GatewayRefundResult,
            gateway=normalized_gateway,
            operation="refund",
            payment_id=getattr(
                payment,
                "pk",
                None,
            ),
            refund_id=getattr(
                refund,
                "pk",
                None,
            ),
        )

        return result

    # ================================================================
    # SETTLEMENT
    # ================================================================

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
        """

        normalized_gateway = cls._normalize_gateway(
            gateway,
        )

        client = cls._client(
            normalized_gateway,
        )

        if not client.supports(
            "settlement",
        ):
            raise PaymentGatewayNotSupportedError(
                "Selected payment gateway does not support settlement.",
                details={
                    "gateway": normalized_gateway.value,
                    "operation": "settlement",
                },
            )

        request = GatewaySettlementRequest(
            amount=cls._normalize_amount(
                amount,
            ),
            authority=cls._normalize_required_string(
                authority,
                field_name="Payment authority",
            ),
            order_id=str(order_id),
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
                    "operation": "settlement",
                },
                retryable=True,
            ) from exc

        cls._require_result_type(
            result=result,
            expected_type=GatewaySettlementResult,
            gateway=normalized_gateway,
            operation="settlement",
        )

        return result

    # ================================================================
    # REVERSAL
    # ================================================================

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

        if not client.supports(
            "reverse",
        ):
            raise PaymentGatewayNotSupportedError(
                "Selected payment gateway does not support reversal.",
                details={
                    "gateway": normalized_gateway.value,
                    "operation": "reverse",
                },
            )

        request = GatewayReverseRequest(
            amount=cls._normalize_amount(
                amount,
            ),
            authority=cls._normalize_required_string(
                authority,
                field_name="Payment authority",
            ),
            order_id=str(order_id),
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
                    "operation": "reverse",
                },
                retryable=True,
            ) from exc

        cls._require_result_type(
            result=result,
            expected_type=GatewayReverseResult,
            gateway=normalized_gateway,
            operation="reverse",
        )

        return result

    # ================================================================
    # INQUIRY
    # ================================================================

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
        Query the current/known gateway transaction state.
        """

        normalized_gateway = cls._normalize_gateway(
            gateway,
        )

        client = cls._client(
            normalized_gateway,
        )

        if not client.supports(
            "inquiry",
        ):
            raise PaymentGatewayNotSupportedError(
                "Selected payment gateway does not support inquiry.",
                details={
                    "gateway": normalized_gateway.value,
                    "operation": "inquiry",
                },
            )

        normalized_amount = (
            None
            if amount is None
            else cls._normalize_amount(
                amount,
            )
        )

        request = GatewayInquiryRequest(
            authority=cls._normalize_required_string(
                authority,
                field_name="Payment authority",
            ),
            order_id=str(order_id),
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
                    "operation": "inquiry",
                },
                retryable=True,
            ) from exc

        cls._require_result_type(
            result=result,
            expected_type=GatewayInquiryResult,
            gateway=normalized_gateway,
            operation="inquiry",
        )

        return result

    # ================================================================
    # CALLBACK
    # ================================================================

    @classmethod
    def parse_callback(
        cls,
        *,
        payload: Mapping[str, Any],
        gateway: PaymentGateway | str,
    ) -> GatewayCallback:
        """
        Parse a provider callback through the selected gateway.

        Callback parsing is deterministic provider logic and does not
        mutate database state.
        """

        normalized_gateway = cls._normalize_gateway(
            gateway,
        )

        client = cls._client(
            normalized_gateway,
        )

        if not client.supports(
            "callback",
        ):
            raise PaymentGatewayNotSupportedError(
                "Selected payment gateway does not support callbacks.",
                details={
                    "gateway": normalized_gateway.value,
                    "operation": "callback",
                },
            )

        if not isinstance(
            payload,
            Mapping,
        ):
            raise PaymentGatewayError(
                "Gateway callback payload must be a mapping.",
                details={
                    "gateway": normalized_gateway.value,
                    "operation": "callback",
                },
                retryable=False,
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
                    "operation": "callback",
                },
                retryable=False,
            ) from exc

        cls._require_result_type(
            result=result,
            expected_type=GatewayCallback,
            gateway=normalized_gateway,
            operation="callback",
        )

        return result

    # ================================================================
    # INTERNAL HELPERS
    # ================================================================

    @classmethod
    def _payment_gateway(
        cls,
        payment: Any,
    ) -> PaymentGateway:
        """
        Resolve the immutable gateway snapshot stored on Payment.
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

    @staticmethod
    def _payment_order_id(
        payment: Any,
    ) -> str:
        """
        Resolve the stable order identifier required by gateways.
        """

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

        if order_id is None:
            order_id = getattr(
                payment,
                "order_id",
                None,
            )

        if order_id is None:
            raise PaymentGatewayError(
                "Payment order is required for gateway operation.",
                details={
                    "payment_id": getattr(
                        payment,
                        "pk",
                        None,
                    ),
                },
                retryable=False,
            )

        return str(order_id)

    @staticmethod
    def _refund_reference(
        refund: Any,
    ) -> str | None:
        """
        Resolve the internal Refund identifier.

        Provider-specific identifiers are never generated here.
        """

        value = getattr(
            refund,
            "pk",
            None,
        )

        if value is None:
            return None

        return str(value)

    @staticmethod
    def _normalize_amount(
        amount: Decimal,
    ) -> Decimal:
        """
        Normalize a financial amount without floating-point arithmetic.
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
                    "operation": "amount_normalization",
                },
                retryable=False,
            ) from exc

        if not normalized.is_finite():
            raise PaymentGatewayError(
                "Financial amount must be finite.",
                details={
                    "operation": "amount_validation",
                },
                retryable=False,
            )

        if normalized <= Decimal("0"):
            raise PaymentGatewayError(
                "Gateway amount must be greater than zero.",
                details={
                    "operation": "amount_validation",
                },
                retryable=False,
            )

        return normalized

    @staticmethod
    def _normalize_currency(
        currency: str | None,
    ) -> str:
        """
        Normalize a currency identifier.

        GatewayService does not implement FX or currency conversion.
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

    @staticmethod
    def _normalize_required_string(
        value: Any,
        *,
        field_name: str,
        details: Mapping[str, Any] | None = None,
    ) -> str:
        """
        Normalize a required textual gateway field.
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


# Commit: stabilize gateway service