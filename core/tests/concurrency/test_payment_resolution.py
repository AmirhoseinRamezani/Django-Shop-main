# tests/concurrency/test_payment_resolution.py
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections, connections, connection

from payment.enums import PaymentStatusType
from payment.models import PaymentResolution, PaymentResolutionReason
from payment.services.payment_resolution import PaymentResolutionService
from tests.factories.order import OrderFactory
from tests.factories.payment import PaymentFactory

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.concurrency]


@pytest.mark.skipif(connection.vendor != "postgresql", reason="Row-lock correctness requires PostgreSQL.")
def test_concurrent_resolution_registration_converges_on_one_row():
    order = OrderFactory(cancelled=True)
    payment = PaymentFactory(order=order, status=PaymentStatusType.SUCCESS, is_consumed=False)
    barrier = Barrier(2)

    def register():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            # Both workers request the same authoritative classification. The
            # service derives the reason from the locked Order row.
            resolution = PaymentResolutionService.register(
                payment_id=payment.pk,
                reason=PaymentResolutionReason.ORDER_CANCELLED,
            )
            return resolution.pk, resolution.reason
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(register),
            executor.submit(register),
        ]
        results = [future.result(timeout=20) for future in futures]

    assert results[0][0] == results[1][0]
    assert PaymentResolution.objects.filter(payment_id=payment.pk).count() == 1
    assert results[0][1] == results[1][1]