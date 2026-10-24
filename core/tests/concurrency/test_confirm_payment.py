# tests/concurrency/test_confirm_payment.py
from __future__ import annotations
import threading

import pytest

from order.events.order_event import OrderEventType
from order.models import OrderStatusType
from order.services.confirm_payment import confirm_order_payment

pytestmark = pytest.mark.django_db(transaction=True)


class TestConcurrentConfirmPayment:

    def test_concurrent_confirm_is_idempotent(
        self,
        order,
        successful_payment,
    ):
        results: list[bool] = []
        errors: list[Exception] = []
        barrier = threading.Barrier(2)

        def worker() -> None:
            try:
                barrier.wait(timeout=10)
                confirm_order_payment(order.id)
                results.append(True)
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(
                target=worker,
                name=f"confirm-payment-{index}",
            )
            for index in range(2)
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join(timeout=15)

        assert all(not thread.is_alive() for thread in threads), (
            "Concurrent confirmation worker did not terminate."
        )

        assert errors == []
        assert len(results) == 2

        order.refresh_from_db()
        successful_payment.refresh_from_db()

        assert order.status == OrderStatusType.paid
        assert order.paid_date is not None
        assert successful_payment.is_consumed is True
        assert (
            order.events
            .filter(type=OrderEventType.PAID)
            .count()
            == 1
        )