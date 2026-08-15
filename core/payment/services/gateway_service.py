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
    GatewayPaymentRequest,
    GatewayPaymentResult,
    GatewayRefundRequest,
    GatewayRefundResult,
    GatewayVerificationRequest,
    GatewayVerificationResult,
)


class GatewayService:
    """
    Application-facing facade for payment gateways.

    GatewayService is responsible for:

    - resolving the selected gateway
    - resolving the registered gateway implementation
    - translating application/domain data into gateway requests
    - executing gateway operations
    - normalizing gateway initialization/execution failures

    It does NOT own:

    - database transactions
    - repository persistence
    - Payment/Refund state transitions
    - business authorization
    - refund balance calculation
    - order mutation
    - gateway log persistence
    """

    # ------------------------------------
    # Gateway resolution
    # ------------------------------------

    @classmethod
    def current_gateway(cls) -> PaymentGateway:
        """
        Return the configured default gateway.

        The returned value is the gateway enum identifier, not the
        concrete implementation class.
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
        Normalize a gateway identifier to PaymentGateway.

        ``None`` means the configured default gateway.
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
        Return whether a gateway is registered and available.
        """

        try:
            normalized = cls._normalize_gateway(gateway)
        except PaymentGatewayError:
            return False

        return GatewayRegistry.is_registered(normalized)

    @classmethod
    def _client(
        cls,
        gateway: PaymentGateway | str | None = None,
    ) -> Any:
        """
        Resolve and instantiate the registered gateway implementation.

        No database work and no network communication occurs here.
        """

        normalized = cls._normalize_gateway(gateway)

        try:
            client_class = GatewayRegistry.resolve(normalized)
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
            return client_class()
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

    # ------------------------------------
    # Payment initiation
    # ------------------------------------

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
        Initiate a payment through the selected gateway.

        The gateway implementation owns provider-specific request
        serialization and communication.

        PaymentAttempt persistence remains outside this service.
        """

        normalized_gateway = cls._normalize_gateway(gateway)

        client = cls._client(normalized_gateway)

        request = GatewayPaymentRequest(
            amount=cls._normalize_amount(amount),
            order_id=str(order_id),
            callback_url=str(callback_url),
            currency=str(currency),
            description=str(description or ""),
            metadata=dict(metadata or {}),
        )

        try:
            result = client.initiate_payment(request)
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

        if not isinstance(result, GatewayPaymentResult):
            raise PaymentGatewayError(
                "Gateway returned an invalid payment result.",
                details={
                    "gateway": normalized_gateway.value,
                    "operation": "initiate_payment",
                },
                retryable=False,
            )

        return result

    # ------------------------------------
    # Payment URL
    # ------------------------------------

    @classmethod
    def payment_url(
        cls,
        authority: str,
        *,
        gateway: PaymentGateway | str | None = None,
    ) -> str:
        """
        Build the user-facing payment URL.

        Provider-specific URL construction remains inside the gateway
        implementation.
        """

        normalized_gateway = cls._normalize_gateway(gateway)
        client = cls._client(normalized_gateway)

        normalized_authority = str(
            authority or ""
        ).strip()

        if not normalized_authority:
            raise PaymentGatewayError(
                "Payment authority is required.",
                details={
                    "gateway": normalized_gateway.value,
                    "operation": "payment_url",
                },
                retryable=False,
            )

        try:
            return client.payment_url(
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

    # ------------------------------------
    # Payment verification
    # ------------------------------------

    @classmethod
    def verify(
        cls,
        payment: Any,
    ) -> GatewayVerificationResult:
        """
        Verify a Payment using the gateway snapshot stored on Payment.

        The Payment's gateway is authoritative. The configured default
        gateway is intentionally ignored for historical payments.
        """

        normalized_gateway = cls._payment_gateway(payment)
        client = cls._client(normalized_gateway)

        amount = cls._normalize_amount(
            payment.amount,
        )

        authority = str(
            getattr(
                payment,
                "authority_id",
                "",
            ) or ""
        ).strip()

        if not authority:
            raise PaymentGatewayError(
                "Payment authority is required for verification.",
                details={
                    "gateway": normalized_gateway.value,
                    "operation": "verify",
                    "payment_id": getattr(
                        payment,
                        "pk",
                        None,
                    ),
                },
                retryable=False,
            )

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
                "",
            )

        request = GatewayVerificationRequest(
            amount=amount,
            authority=authority,
            order_id=str(order_id),
            currency=str(
                getattr(
                    payment,
                    "currency",
                    Currency.IRR,
                )
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

        if not isinstance(
            result,
            GatewayVerificationResult,
        ):
            raise PaymentGatewayError(
                "Gateway returned an invalid verification result.",
                details={
                    "gateway": normalized_gateway.value,
                    "operation": "verify",
                    "payment_id": getattr(
                        payment,
                        "pk",
                        None,
                    ),
                },
                retryable=False,
            )

        return result

    # ------------------------------------
    # Refund
    # ------------------------------------

    @classmethod
    def refund(
        cls,
        *,
        payment: Any,
        refund: Any,
        gateway: PaymentGateway | str | None = None,
    ) -> GatewayRefundResult:
        """
        Execute a refund through the gateway associated with the Payment.

        The Payment gateway is authoritative unless an explicit gateway
        is supplied by the application.

        Refund authorization, cumulative refund validation and Payment
        state mutation remain outside this service.
        """

        normalized_gateway = (
            cls._payment_gateway(payment)
            if gateway is None
            else cls._normalize_gateway(gateway)
        )

        client = cls._client(
            normalized_gateway,
        )

        if not client.supports("refund"):
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

        authority = str(
            getattr(
                payment,
                "authority_id",
                "",
            ) or ""
        ).strip()

        if not authority:
            raise PaymentGatewayError(
                "Payment authority is required for refund.",
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
                retryable=False,
            )

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
                "",
            )

        request = GatewayRefundRequest(
            amount=amount,
            authority=authority,
            order_id=str(order_id),
            currency=str(
                getattr(
                    refund,
                    "currency",
                    getattr(
                        payment,
                        "currency",
                        Currency.IRR,
                    ),
                )
            ),
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

        if not isinstance(
            result,
            GatewayRefundResult,
        ):
            raise PaymentGatewayError(
                "Gateway returned an invalid refund result.",
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
                retryable=False,
            )

        return result

    # ------------------------------------
    # Internal helpers
    # ------------------------------------

    @classmethod
    def _payment_gateway(
        cls,
        payment: Any,
    ) -> PaymentGateway:
        """
        Resolve the gateway snapshot stored on a Payment.
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
    def _refund_reference(
        refund: Any,
    ) -> str | None:
        """
        Resolve an optional internal refund reference without exposing
        provider-specific identifiers.
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

        if normalized <= Decimal("0"):
            raise PaymentGatewayError(
                "Gateway amount must be greater than zero.",
                details={
                    "operation": "amount_validation",
                },
                retryable=False,
            )

        return normalized