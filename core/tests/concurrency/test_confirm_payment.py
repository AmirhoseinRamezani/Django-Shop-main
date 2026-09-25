# tests/concurrency/test_confirm_payment.py
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
        results = []
        errors = []

        def worker():
            try:
                confirm_order_payment(order.id)
                results.append(True)

            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)

        t1.start()
        t2.start()

        t1.join()
        t2.join()

        order.refresh_from_db()
        successful_payment.refresh_from_db()

        assert len(results) == 2
        assert errors == []

        assert successful_payment.is_consumed
        assert order.status == OrderStatusType.paid
        assert order.events.filter(type=OrderEventType.PAID).count() == 1