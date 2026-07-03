# tests/e2e/test_retry_payment.py
import pytest

from payment.services.services import PaymentService


pytestmark = pytest.mark.django_db


def test_cannot_create_second_pending_payment(
    order,
    payment,
):

    with pytest.raises(Exception):

        PaymentService.start_payment(order)