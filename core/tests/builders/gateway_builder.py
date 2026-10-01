# core/tests/builders/gateway_builder.py
"""
Gateway builder for payment integration testing.
"""

from typing import Any, Dict, Optional


class GatewayBuilder:
    """Builder for mock gateway responses and configuration."""

    def __init__(self) -> None:
        self._success: bool = True
        self._authority_id: str = "AUTH-TEST-12345"
        self._gateway_reference: str = "REF-TEST-67890"
        self._gateway_transaction_id: str = "TXN-TEST-11111"
        self._response_code: int = 100
        self._gateway_message: str = "Operation successful"
        self._extra_data: Dict[str, Any] = {}

    def with_authority(self, authority_id: str) -> "GatewayBuilder":
        self._authority_id = authority_id
        return self

    def with_reference(self, reference: str) -> "GatewayBuilder":
        self._gateway_reference = reference
        return self

    def with_transaction_id(self, txn_id: str) -> "GatewayBuilder":
        self._gateway_transaction_id = txn_id
        return self

    def failed(
        self, message: str = "Transaction failed", code: int = -1
    ) -> "GatewayBuilder":
        self._success = False
        self._response_code = code
        self._gateway_message = message
        return self

    def with_extra_data(self, **kwargs: Any) -> "GatewayBuilder":
        self._extra_data.update(kwargs)
        return self

    def build_request_payload(self) -> Dict[str, Any]:
        return {
            "merchant_id": "TEST-MERCHANT",
            "amount": 100000,
            "callback_url": "https://example.com/callback",
            "description": "Test Transaction",
        }

    def build_response_payload(self) -> Dict[str, Any]:
        if self._success:
            return {
                "status": self._response_code,
                "authority": self._authority_id,
                "ref_id": self._gateway_reference,
                "trans_id": self._gateway_transaction_id,
                "message": self._gateway_message,
                **self._extra_data,
            }
        return {
            "status": self._response_code,
            "message": self._gateway_message,
            "errors": [self._gateway_message],
            **self._extra_data,
        }

    def build(self) -> Dict[str, Any]:
        return {
            "success": self._success,
            "authority_id": self._authority_id,
            "gateway_reference": self._gateway_reference,
            "gateway_transaction_id": self._gateway_transaction_id,
            "response_code": self._response_code,
            "gateway_message": self._gateway_message,
            "request_payload": self.build_request_payload(),
            "response_payload": self.build_response_payload(),
        }