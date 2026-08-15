# core/payment/providers/base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Mapping

from payment.enums import PaymentGateway
from payment.exceptions import (
    PaymentGatewayNotSupportedError,
)


@dataclass(frozen=True, slots=True)
class GatewayPaymentRequest:
    """
    Provider-independent payment initiation request.

    Provider-specific credentials, protocol details and serialization
    must remain inside the concrete gateway implementation.
    """

    amount: Decimal
    order_id: str
    callback_url: str

    currency: str = "IRR"
    description: str = ""

    metadata: Mapping[str, Any] = field(
        default_factory=dict,
    )


@dataclass(frozen=True, slots=True)
class GatewayPaymentResult:
    """
    Normalized result of a payment initiation request.
    """

    success: bool

    gateway: PaymentGateway

    authority: str | None = None

    gateway_reference: str | None = None

    gateway_transaction_id: str | None = None

    response_code: str | None = None

    message: str | None = None

    raw: Mapping[str, Any] = field(
        default_factory=dict,
    )


@dataclass(frozen=True, slots=True)
class GatewayVerificationRequest:
    """
    Provider-independent payment verification request.
    """

    amount: Decimal
    authority: str
    order_id: str

    currency: str = "IRR"


@dataclass(frozen=True, slots=True)
class GatewayVerificationResult:
    """
    Normalized payment verification result.
    """

    success: bool

    gateway: PaymentGateway

    gateway_reference: str | None = None

    gateway_transaction_id: str | None = None

    response_code: str | None = None

    message: str | None = None

    amount: Decimal | None = None

    currency: str | None = None

    raw: Mapping[str, Any] = field(
        default_factory=dict,
    )


@dataclass(frozen=True, slots=True)
class GatewaySettlementRequest:
    """
    Provider-independent settlement request.

    Not every gateway supports settlement explicitly.
    """

    amount: Decimal
    authority: str
    order_id: str

    currency: str = "IRR"


@dataclass(frozen=True, slots=True)
class GatewaySettlementResult:
    """
    Normalized settlement result.
    """

    success: bool

    gateway: PaymentGateway

    gateway_reference: str | None = None

    gateway_transaction_id: str | None = None

    response_code: str | None = None

    message: str | None = None

    raw: Mapping[str, Any] = field(
        default_factory=dict,
    )


@dataclass(frozen=True, slots=True)
class GatewayRefundRequest:
    """
    Provider-independent refund request.
    """

    amount: Decimal
    authority: str
    order_id: str

    currency: str = "IRR"

    refund_reference: str | None = None


@dataclass(frozen=True, slots=True)
class GatewayRefundResult:
    """
    Normalized refund result.
    """

    success: bool

    gateway: PaymentGateway

    gateway_reference: str | None = None

    gateway_transaction_id: str | None = None

    response_code: str | None = None

    message: str | None = None

    raw: Mapping[str, Any] = field(
        default_factory=dict,
    )


@dataclass(frozen=True, slots=True)
class GatewayReverseRequest:
    """
    Provider-independent payment reversal request.
    """

    amount: Decimal
    authority: str
    order_id: str

    currency: str = "IRR"


@dataclass(frozen=True, slots=True)
class GatewayReverseResult:
    """
    Normalized payment reversal result.
    """

    success: bool

    gateway: PaymentGateway

    gateway_reference: str | None = None

    gateway_transaction_id: str | None = None

    response_code: str | None = None

    message: str | None = None

    raw: Mapping[str, Any] = field(
        default_factory=dict,
    )


@dataclass(frozen=True, slots=True)
class GatewayInquiryRequest:
    """
    Provider-independent transaction inquiry request.

    Inquiry is intentionally separate from verification.

    Verification answers:
        "Can this payment be accepted as a successful payment?"

    Inquiry answers:
        "What is the current/known state of this gateway transaction?"

    Some gateways, including Behpardakht Mellat, expose inquiry
    as a distinct gateway operation.
    """

    authority: str
    order_id: str

    amount: Decimal | None = None

    currency: str = "IRR"


@dataclass(frozen=True, slots=True)
class GatewayInquiryResult:
    """
    Normalized gateway transaction inquiry result.
    """

    success: bool

    gateway: PaymentGateway

    gateway_reference: str | None = None

    gateway_transaction_id: str | None = None

    response_code: str | None = None

    message: str | None = None

    amount: Decimal | None = None

    currency: str | None = None

    raw: Mapping[str, Any] = field(
        default_factory=dict,
    )


@dataclass(frozen=True, slots=True)
class GatewayCallback:
    """
    Provider-independent normalized callback.

    The concrete gateway implementation is responsible for translating
    provider-specific callback parameters into this structure.
    """

    gateway: PaymentGateway

    authority: str | None = None

    order_id: str | None = None

    gateway_reference: str | None = None

    gateway_transaction_id: str | None = None

    response_code: str | None = None

    success: bool | None = None

    message: str | None = None

    data: Mapping[str, Any] = field(
        default_factory=dict,
    )


class GatewayCapabilities:
    """
    Declares optional capabilities exposed by a gateway.

    Payment initiation, payment URL generation, verification and
    callback parsing are mandatory BaseGateway operations.

    Settlement, refund, reversal and inquiry are optional because
    gateway support differs.
    """

    __slots__ = (
        "refund",
        "settlement",
        "reverse",
        "inquiry",
        "callback",
    )

    def __init__(
        self,
        *,
        refund: bool = False,
        settlement: bool = False,
        reverse: bool = False,
        inquiry: bool = False,
        callback: bool = True,
    ) -> None:
        self.refund = refund
        self.settlement = settlement
        self.reverse = reverse
        self.inquiry = inquiry
        self.callback = callback

    def supports(
        self,
        operation: str,
    ) -> bool:
        try:
            return bool(
                getattr(
                    self,
                    operation,
                )
            )
        except AttributeError:
            return False

    def __repr__(self) -> str:
        return (
            "GatewayCapabilities("
            f"refund={self.refund!r}, "
            f"settlement={self.settlement!r}, "
            f"reverse={self.reverse!r}, "
            f"inquiry={self.inquiry!r}, "
            f"callback={self.callback!r}"
            ")"
        )


class BaseGateway(ABC):
    """
    Provider contract for payment gateways.

    Concrete implementations are responsible for:

    - gateway-specific authentication
    - HTTP/SOAP communication
    - provider-specific request serialization
    - provider-specific response parsing
    - provider-specific callback parsing

    They must return normalized payment-layer result objects.
    """

    gateway: PaymentGateway

    capabilities = GatewayCapabilities()

    # ------------------------------------
    # Core identity
    # ------------------------------------

    @property
    def name(self) -> str:
        return self.gateway.value

    # ------------------------------------
    # Required payment operations
    # ------------------------------------

    @abstractmethod
    def initiate_payment(
        self,
        request: GatewayPaymentRequest,
    ) -> GatewayPaymentResult:
        raise NotImplementedError

    @abstractmethod
    def payment_url(
        self,
        authority: str,
    ) -> str:
        raise NotImplementedError

    @abstractmethod
    def verify_payment(
        self,
        request: GatewayVerificationRequest,
    ) -> GatewayVerificationResult:
        raise NotImplementedError

    @abstractmethod
    def parse_callback(
        self,
        payload: Mapping[str, Any],
    ) -> GatewayCallback:
        raise NotImplementedError

    # ------------------------------------
    # Optional settlement
    # ------------------------------------

    def settle_payment(
        self,
        request: GatewaySettlementRequest,
    ) -> GatewaySettlementResult:
        self._require_capability(
            "settlement",
        )

        raise NotImplementedError(
            "Settlement capability is declared but not implemented."
        )

    # ------------------------------------
    # Optional refund
    # ------------------------------------

    def refund(
        self,
        request: GatewayRefundRequest,
    ) -> GatewayRefundResult:
        self._require_capability(
            "refund",
        )

        raise NotImplementedError(
            "Refund capability is declared but not implemented."
        )

    # ------------------------------------
    # Optional reversal
    # ------------------------------------

    def reverse_payment(
        self,
        request: GatewayReverseRequest,
    ) -> GatewayReverseResult:
        self._require_capability(
            "reverse",
        )

        raise NotImplementedError(
            "Reverse capability is declared but not implemented."
        )

    # ------------------------------------
    # Optional inquiry
    # ------------------------------------

    def inquire_payment(
        self,
        request: GatewayInquiryRequest,
    ) -> GatewayInquiryResult:
        """
        Query the current/known gateway state of a transaction.

        Inquiry is deliberately separate from verification because
        some providers expose both operations with different semantics.
        """

        self._require_capability(
            "inquiry",
        )

        raise NotImplementedError(
            "Inquiry capability is declared but not implemented."
        )

    # ------------------------------------
    # Capability helpers
    # ------------------------------------

    def supports(
        self,
        operation: str,
    ) -> bool:
        return self.capabilities.supports(
            operation,
        )

    def _require_capability(
        self,
        operation: str,
    ) -> None:
        if not self.supports(operation):
            raise PaymentGatewayNotSupportedError(
                "Payment gateway does not support this operation.",
                details={
                    "gateway": self.gateway.value,
                    "operation": operation,
                },
            )