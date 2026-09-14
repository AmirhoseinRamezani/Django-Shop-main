import pytest

from payment.enums import PaymentAttemptStatus
from payment.services.callback import resolve_callback

from tests.factories.payment import PaymentAttemptFactory


pytestmark = pytest.mark.django_db


def test_callback_resolves_exact_retry_attempt(payment):
    first_attempt = PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        retry_count=1,
        status=PaymentAttemptStatus.FAILED,
        authority_id="AUTH-1",
    )
    second_attempt = PaymentAttemptFactory(
        payment=payment,
        attempt_number=2,
        retry_count=2,
        status=PaymentAttemptStatus.PENDING,
        authority_id="AUTH-2",
        retry_of=first_attempt,
    )

    resolution = resolve_callback(authority="AUTH-1")

    assert resolution.payment_id == payment.pk
    assert resolution.attempt_id == first_attempt.pk
    assert resolution.attempt_id != second_attempt.pk


def test_callback_resolves_new_attempt_by_its_own_authority(payment):
    first_attempt = PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        retry_count=1,
        status=PaymentAttemptStatus.FAILED,
        authority_id="AUTH-1",
    )
    second_attempt = PaymentAttemptFactory(
        payment=payment,
        attempt_number=2,
        retry_count=2,
        status=PaymentAttemptStatus.PENDING,
        authority_id="AUTH-2",
        retry_of=first_attempt,
    )

    resolution = resolve_callback(authority="AUTH-2")

    assert resolution.attempt_id == second_attempt.pk
