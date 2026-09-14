# core/payment/services/callback.py
"""Gateway callback identity resolution.

This module is the provider-to-application identity boundary.

A callback authority belongs to exactly one PaymentAttempt.  The resolver
returns both the owning Payment and the concrete Attempt so the verification
workflow can never silently switch to another attempt for the same Payment.
"""

from __future__ import annotations

from dataclasses import dataclass

from payment.enums import PaymentGateway
from payment.exceptions import (
    PaymentCallbackIdentityMismatchError,
    PaymentCallbackMissingIdentityError,
    PaymentInvalidCallbackError,
)
from payment.repositories.payment_attempt_repository import PaymentAttemptRepository


@dataclass(frozen=True, slots=True)
class CallbackResolution:
    """Trusted local identity resolved from an untrusted callback authority."""

    payment_id: int
    attempt_id: int
    gateway: PaymentGateway
    authority: str


def _normalize_authority(authority: str | None) -> str:
    normalized = str(authority or "").strip()
    if not normalized:
        raise PaymentCallbackMissingIdentityError(
            "Gateway callback authority is required."
        )
    return normalized


def _normalize_gateway(
    value: PaymentGateway | str,
) -> PaymentGateway:
    try:
        return (
            value
            if isinstance(value, PaymentGateway)
            else PaymentGateway(
                getattr(value, "value", str(value)).strip()
            )
        )
    except (TypeError, ValueError) as exc:
        raise PaymentCallbackIdentityMismatchError(
            "Gateway callback gateway is invalid."
        ) from exc


def resolve_callback(
    *,
    authority: str | None,
    gateway: PaymentGateway | str | None = None,
) -> CallbackResolution:
    """Resolve a callback authority to exactly one PaymentAttempt.

    Resolution is intentionally persistence-only.  It does not verify the
    payment and does not mutate financial state.

    If a gateway is supplied, it is an additional identity assertion.  A
    callback must never be allowed to resolve to an attempt belonging to a
    different historical gateway.
    """

    normalized_authority = _normalize_authority(authority)

    matches = list(
        PaymentAttemptRepository.for_authority(
            normalized_authority,
        )[:2]
    )

    if not matches:
        raise PaymentInvalidCallbackError(
            "Gateway callback authority does not match a known PaymentAttempt."
        )

    if len(matches) > 1:
        raise PaymentCallbackIdentityMismatchError(
            "Gateway callback authority matches multiple PaymentAttempts."
        )

    attempt = matches[0]

    if attempt.payment_id is None:
        raise PaymentInvalidCallbackError(
            "Gateway callback PaymentAttempt has no Payment owner."
        )

    payment = attempt.payment
    if payment is None:
        raise PaymentInvalidCallbackError(
            "Gateway callback PaymentAttempt has no Payment owner."
        )

    if gateway is not None:
        expected_gateway = _normalize_gateway(gateway)
        actual_gateway = _normalize_gateway(payment.gateway)

        if actual_gateway != expected_gateway:
            raise PaymentCallbackIdentityMismatchError(
                "Gateway callback gateway does not match the Payment gateway."
            )

    actual_gateway = _normalize_gateway(payment.gateway)

    return CallbackResolution(
        payment_id=attempt.payment_id,
        attempt_id=attempt.pk,
        gateway=actual_gateway,
        authority=normalized_authority,
    )


def resolve_payment_id(*, authority: str | None) -> int:
    """Compatibility wrapper returning only the owning Payment id.

    New callback entrypoints should use :func:`resolve_callback` so the
    concrete PaymentAttempt identity is preserved through verification.
    """

    return resolve_callback(
        authority=authority,
    ).payment_id
