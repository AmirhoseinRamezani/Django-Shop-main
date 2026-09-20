from decimal import Decimal

import pytest

from payment.enums import PaymentGateway, RefundStatus
from payment.exceptions import PaymentGatewayNotSupportedError
from payment.providers.base import (
    BaseGateway,
    GatewayCallback,
    GatewayCapabilities,
    GatewayPaymentRequest,
    GatewayPaymentResult,
    GatewayRefundInquiryRequest,
    GatewayRefundInquiryResult,
    GatewayRefundRequest,
    GatewayRefundResult,
    GatewayVerificationRequest,
    GatewayVerificationResult,
)


class ContractGateway(BaseGateway):
    gateway = PaymentGateway.PAYPAL

    capabilities = GatewayCapabilities(
        refund=True,
        refund_inquiry=True,
        refund_idempotency=True,
    )

    def initiate_payment(
        self,
        request: GatewayPaymentRequest,
    ) -> GatewayPaymentResult:
        raise NotImplementedError

    def payment_url(self, authority: str) -> str:
        raise NotImplementedError

    def verify_payment(
        self,
        request: GatewayVerificationRequest,
    ) -> GatewayVerificationResult:
        raise NotImplementedError

    def parse_callback(
        self,
        payload: dict,
    ) -> GatewayCallback:
        raise NotImplementedError

    def refund(
        self,
        request: GatewayRefundRequest,
    ) -> GatewayRefundResult:
        return GatewayRefundResult(
            success=True,
            status=RefundStatus.SUCCESS,
            gateway=self.gateway,
            gateway_reference="refund-ref",
        )

    def inquire_refund(
        self,
        request: GatewayRefundInquiryRequest,
    ) -> GatewayRefundInquiryResult:
        return GatewayRefundInquiryResult(
            success=True,
            gateway=self.gateway,
            gateway_reference="refund-ref",
            amount=request.amount,
            currency=request.currency,
        )


class RefundOnlyGateway(ContractGateway):
    capabilities = GatewayCapabilities(
        refund=True,
    )


def test_refund_request_carries_provider_idempotency_identity():
    request = GatewayRefundRequest(
        amount=Decimal("100000"),
        authority="AUTH-1",
        order_id="ORDER-1",
        refund_reference="42",
        idempotency_key="refund-idempotency-1",
    )

    assert request.refund_reference == "42"
    assert request.idempotency_key == "refund-idempotency-1"


def test_refund_inquiry_is_separate_from_payment_inquiry():
    gateway = ContractGateway()

    request = GatewayRefundInquiryRequest(
        refund_reference="42",
        gateway_reference="refund-ref",
        authority="AUTH-1",
        order_id="ORDER-1",
        amount=Decimal("100000"),
        currency="IRR",
    )

    result = gateway.inquire_refund(request)

    assert result.success is True
    assert result.status == RefundStatus.SUCCESS
    assert result.gateway == PaymentGateway.PAYPAL
    assert result.gateway_reference == "refund-ref"
    assert result.amount == Decimal("100000")


def test_refund_inquiry_requires_explicit_provider_capability():
    gateway = RefundOnlyGateway()

    with pytest.raises(PaymentGatewayNotSupportedError):
        gateway.inquire_refund(
            GatewayRefundInquiryRequest(
                refund_reference="42",
            )
        )


def test_refund_idempotency_is_explicit_capability():
    assert ContractGateway.capabilities.supports(
        "refund_idempotency"
    )
    assert not RefundOnlyGateway.capabilities.supports(
        "refund_idempotency"
    )
