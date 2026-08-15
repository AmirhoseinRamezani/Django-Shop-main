# core/payment/gateways/zarinpal.py

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

import requests
from django.conf import settings

from payment.enums import Currency, PaymentGateway
from payment.exceptions import (
    PaymentGatewayError,
    PaymentGatewayNotSupportedError,
)
from payment.providers.base import (
    BaseGateway,
    GatewayCallback,
    GatewayCapabilities,
    GatewayPaymentRequest,
    GatewayPaymentResult,
    GatewayRefundRequest,
    GatewayRefundResult,
    GatewayVerificationRequest,
    GatewayVerificationResult,
)


class ZarinPalGateway(BaseGateway):
    """
    ZarinPal V4 gateway adapter.
    This class contains only provider-specific communication and
    response normalization.

    It does not perform:
    - database operations
    - transactions
    - Payment persistence
    - Refund persistence
    - business authorization
    - payment/refund state transitions
    """

    gateway = PaymentGateway.ZARINPAL

    capabilities = GatewayCapabilities(
        refund=False,
        settlement=False,
        reverse=False,
        callback=True,
    )

    LIVE_API_BASE_URL = (
        "https://api.zarinpal.com/pg/v4"
    )

    SANDBOX_API_BASE_URL = (
        "https://sandbox.zarinpal.com/pg/rest/WebGate"
    )

    LIVE_PAYMENT_URL = (
        "https://www.zarinpal.com/pg/StartPay/"
    )

    SANDBOX_PAYMENT_URL = (
        "https://sandbox.zarinpal.com/pg/StartPay/"
    )

    REQUEST_PATH = "/payment/request.json"

    VERIFY_PATH = "/payment/verify.json"

    DEFAULT_TIMEOUT = (5.0, 20.0)

    def __init__(
        self,
        *,
        merchant_id: str | None = None,
        sandbox: bool | None = None,
        timeout: tuple[float, float] | float | None = None,
        session: requests.Session | None = None,
    ) -> None:
        configured_merchant_id = (
            merchant_id
            if merchant_id is not None
            else getattr(
                settings,
                "ZARINPAL_MERCHANT_ID",
                getattr(
                    settings,
                    "MERCHANT_ID",
                    "",
                ),
            )
        )

        normalized_merchant_id = str(
            configured_merchant_id or ""
        ).strip()

        if not normalized_merchant_id:
            raise PaymentGatewayError(
                "ZarinPal merchant ID is not configured.",
                details={
                    "gateway": self.gateway.value,
                    "setting": "ZARINPAL_MERCHANT_ID",
                },
                retryable=False,
            )

        configured_sandbox = (
            sandbox
            if sandbox is not None
            else getattr(
                settings,
                "ZARINPAL_SANDBOX",
                True,
            )
        )

        self.merchant_id = normalized_merchant_id
        self.sandbox = bool(configured_sandbox)
        self.timeout = (
            timeout
            if timeout is not None
            else self.DEFAULT_TIMEOUT
        )
        self.session = (
            session
            if session is not None
            else requests.Session()
        )

    # ------------------------------------
    # BaseGateway
    # ------------------------------------

    def initiate_payment(
        self,
        request: GatewayPaymentRequest,
    ) -> GatewayPaymentResult:
        amount = self._normalize_amount(
            request.amount,
        )

        currency = self._normalize_currency(
            request.currency,
        )

        if currency != Currency.IRR:
            raise PaymentGatewayError(
                "ZarinPal currently requires IRR payments.",
                details={
                    "gateway": self.gateway.value,
                    "currency": currency,
                },
                retryable=False,
            )

        payload = {
            "merchant_id": self.merchant_id,
            "amount": int(amount),
            "callback_url": str(
                request.callback_url,
            ),
            "description": str(
                request.description or ""
            ),
        }

        if request.metadata:
            payload["metadata"] = dict(
                request.metadata,
            )

        response = self._post(
            path=self.REQUEST_PATH,
            payload=payload,
            operation="initiate_payment",
        )

        data = self._response_data(
            response,
        )

        code = self._response_code(
            data,
        )

        authority = self._string_value(
            data.get("authority"),
        )

        message = self._response_message(
            response,
        )

        success = (
            code == 100
            and bool(authority)
        )

        return GatewayPaymentResult(
            success=success,
            gateway=self.gateway,
            authority=authority or None,
            response_code=(
                str(code)
                if code is not None
                else None
            ),
            message=message,
            raw=response,
        )

    def payment_url(
        self,
        authority: str,
    ) -> str:
        normalized_authority = str(
            authority or ""
        ).strip()

        if not normalized_authority:
            raise PaymentGatewayError(
                "ZarinPal authority is required.",
                details={
                    "gateway": self.gateway.value,
                    "operation": "payment_url",
                },
                retryable=False,
            )

        base_url = (
            self.SANDBOX_PAYMENT_URL
            if self.sandbox
            else self.LIVE_PAYMENT_URL
        )

        return f"{base_url}{normalized_authority}"

    def verify_payment(
        self,
        request: GatewayVerificationRequest,
    ) -> GatewayVerificationResult:
        amount = self._normalize_amount(
            request.amount,
        )

        currency = self._normalize_currency(
            request.currency,
        )

        if currency != Currency.IRR:
            raise PaymentGatewayError(
                "ZarinPal currently requires IRR verification.",
                details={
                    "gateway": self.gateway.value,
                    "currency": currency,
                },
                retryable=False,
            )

        authority = str(
            request.authority or ""
        ).strip()

        if not authority:
            raise PaymentGatewayError(
                "ZarinPal authority is required.",
                details={
                    "gateway": self.gateway.value,
                    "operation": "verify",
                },
                retryable=False,
            )

        payload = {
            "merchant_id": self.merchant_id,
            "amount": int(amount),
            "authority": authority,
        }

        response = self._post(
            path=self.VERIFY_PATH,
            payload=payload,
            operation="verify",
        )

        data = self._response_data(
            response,
        )

        code = self._response_code(
            data,
        )

        ref_id = self._string_value(
            data.get("ref_id"),
        )

        message = self._response_message(
            response,
        )

        return GatewayVerificationResult(
            success=code in {100, 101},
            gateway=self.gateway,
            gateway_reference=ref_id or None,
            response_code=(
                str(code)
                if code is not None
                else None
            ),
            message=message,
            amount=amount,
            currency=currency,
            raw=response,
        )

    def parse_callback(
        self,
        payload: Mapping[str, Any],
    ) -> GatewayCallback:
        """
        Normalize ZarinPal callback parameters.

        ZarinPal commonly redirects to the merchant callback with:

            Authority
            Status

        The callback itself is NOT considered proof of payment.
        Verification must still be performed through the gateway API.
        """

        authority = self._first_value(
            payload,
            "Authority",
            "authority",
        )

        status = self._first_value(
            payload,
            "Status",
            "status",
        )

        normalized_authority = self._string_value(
            authority,
        )

        normalized_status = self._string_value(
            status,
        )

        success = None

        if normalized_status:
            success = (
                normalized_status.upper()
                == "OK"
            )

        return GatewayCallback(
            gateway=self.gateway,
            authority=(
                normalized_authority
                or None
            ),
            success=success,
            response_code=(
                normalized_status
                or None
            ),
            data=dict(payload),
        )

    # ------------------------------------
    # Refund
    # ------------------------------------

    def refund(
        self,
        request: GatewayRefundRequest,
    ) -> GatewayRefundResult:
        """
        ZarinPal refund is intentionally not implemented here yet.

        The current BaseGateway contract supports refund capability,
        but the payment implementation must not claim support until
        the exact provider refund API and its financial semantics are
        integrated and tested.
        """

        self._require_capability(
            "refund",
        )

        raise PaymentGatewayNotSupportedError(
            "ZarinPal refund is not implemented.",
            details={
                "gateway": self.gateway.value,
                "operation": "refund",
            },
        )

    # ------------------------------------
    # HTTP transport
    # ------------------------------------

    def _post(
        self,
        *,
        path: str,
        payload: Mapping[str, Any],
        operation: str,
    ) -> Mapping[str, Any]:
        url = self._api_url(
            path,
        )

        try:
            response = self.session.post(
                url,
                json=dict(payload),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            raise PaymentGatewayError(
                "ZarinPal request timed out.",
                details={
                    "gateway": self.gateway.value,
                    "operation": operation,
                },
                retryable=True,
            ) from exc
        except requests.RequestException as exc:
            raise PaymentGatewayError(
                "ZarinPal request failed.",
                details={
                    "gateway": self.gateway.value,
                    "operation": operation,
                },
                retryable=True,
            ) from exc

        if response.status_code >= 500:
            raise PaymentGatewayError(
                "ZarinPal service is temporarily unavailable.",
                details={
                    "gateway": self.gateway.value,
                    "operation": operation,
                    "http_status": response.status_code,
                },
                retryable=True,
            )

        if response.status_code >= 400:
            raise PaymentGatewayError(
                "ZarinPal rejected the HTTP request.",
                details={
                    "gateway": self.gateway.value,
                    "operation": operation,
                    "http_status": response.status_code,
                },
                retryable=False,
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise PaymentGatewayError(
                "ZarinPal returned an invalid JSON response.",
                details={
                    "gateway": self.gateway.value,
                    "operation": operation,
                },
                retryable=False,
            ) from exc

        if not isinstance(data, Mapping):
            raise PaymentGatewayError(
                "ZarinPal returned an invalid response structure.",
                details={
                    "gateway": self.gateway.value,
                    "operation": operation,
                },
                retryable=False,
            )

        return data

    # ------------------------------------
    # Configuration
    # ------------------------------------

    def _api_url(
        self,
        path: str,
    ) -> str:
        base_url = (
            self.SANDBOX_API_BASE_URL
            if self.sandbox
            else self.LIVE_API_BASE_URL
        )

        return (
            f"{base_url.rstrip('/')}/"
            f"{path.lstrip('/')}"
        )

    # ------------------------------------
    # Response normalization
    # ------------------------------------

    @staticmethod
    def _response_data(
        response: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        data = response.get(
            "data",
        )

        if isinstance(data, Mapping):
            return data

        return {}

    @staticmethod
    def _response_code(
        data: Mapping[str, Any],
    ) -> int | None:
        value = data.get(
            "code",
        )

        if value is None:
            return None

        try:
            return int(value)
        except (
            TypeError,
            ValueError,
        ):
            return None

    @staticmethod
    def _response_message(
        response: Mapping[str, Any],
    ) -> str | None:
        errors = response.get(
            "errors",
        )

        if isinstance(errors, Mapping):
            message = errors.get(
                "message",
            )

            if message:
                return str(
                    message,
                )[:255]

        data = response.get(
            "data",
        )

        if isinstance(data, Mapping):
            message = data.get(
                "message",
            )

            if message:
                return str(
                    message,
                )[:255]

        message = response.get(
            "message",
        )

        if message:
            return str(
                message,
            )[:255]

        return None

    @staticmethod
    def _first_value(
        payload: Mapping[str, Any],
        *keys: str,
    ) -> Any:
        for key in keys:
            if key in payload:
                return payload[key]

        return None

    @staticmethod
    def _string_value(
        value: Any,
    ) -> str:
        if value is None:
            return ""

        return str(
            value,
        ).strip()

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
                "Invalid financial amount.",
                details={
                    "gateway": PaymentGateway.ZARINPAL.value,
                },
                retryable=False,
            ) from exc

        if normalized <= Decimal("0"):
            raise PaymentGatewayError(
                "Gateway amount must be greater than zero.",
                details={
                    "gateway": PaymentGateway.ZARINPAL.value,
                },
                retryable=False,
            )

        if normalized != normalized.to_integral_value():
            raise PaymentGatewayError(
                "ZarinPal amount must be an integer Rial value.",
                details={
                    "gateway": PaymentGateway.ZARINPAL.value,
                },
                retryable=False,
            )

        return normalized

    @staticmethod
    def _normalize_currency(
        currency: str,
    ) -> str:
        return str(
            currency or Currency.IRR,
        ).strip().upper()