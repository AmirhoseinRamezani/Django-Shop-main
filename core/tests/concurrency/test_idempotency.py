import pytest

from order.services.inventory import InventoryService
from payment.services.verify import verify_payment

pytestmark = pytest.mark.django_db


def test_verify_twice_returns_same_payment(successful_payment):
    attempt = successful_payment.attempts.get()

    InventoryService.reserve(successful_payment.order)

    first = verify_payment(
        payment_id=successful_payment.pk,
        attempt_id=attempt.pk,
        ref_id="REF-SUCCESSFUL",
    )
    second = verify_payment(
        payment_id=successful_payment.pk,
        attempt_id=attempt.pk,
        ref_id="REF-SUCCESSFUL",
    )

    assert first.pk == second.pk == successful_payment.pk
    successful_payment.refresh_from_db()
    assert successful_payment.is_consumed is True
