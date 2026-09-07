# core/payment/services/callback.py
"""Gateway callback identity resolution.

The callback adapter translates provider-facing identity into the internal
Payment identifier required by the authoritative verification service.

It deliberately does not verify or mutate financial state.
"""

from __future__ import annotations

from payment.exceptions import (
    PaymentCallbackIdentityMismatchError,
    PaymentCallbackMissingIdentityError,
    PaymentInvalidCallbackError,
)
from payment.repositories.payment_attempt_repository import PaymentAttemptRepository


def resolve_payment_id(*, authority: str | None) -> int:
    """Resolve a provider callback authority to exactly one Payment."""

    normalized = str(authority or "").strip()
    if not normalized:
        raise PaymentCallbackMissingIdentityError(
            "Gateway callback authority is required."
        )

    matches = list(
        PaymentAttemptRepository.for_authority(normalized)[:2]
    )

    if not matches:
        raise PaymentInvalidCallbackError(
            "Gateway callback authority does not match a known PaymentAttempt."
        )

    if len(matches) > 1:
        # A provider authority is expected to identify one concrete gateway
        # execution.  Ambiguity must never be resolved by picking a row.
        raise PaymentCallbackIdentityMismatchError(
            "Gateway callback authority matches multiple PaymentAttempts."
        )

    attempt = matches[0]
    if attempt.payment_id is None:
        raise PaymentInvalidCallbackError(
            "Gateway callback PaymentAttempt has no Payment owner."
        )

    return attempt.payment_id