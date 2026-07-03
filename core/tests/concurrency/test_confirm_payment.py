# tests/concurrency/test_confirm_payment.py
import threading

import pytest

from django.core.exceptions import ValidationError

from order.services.confirm_payment import confirm_order_payment

pytestmark = pytest.mark.django_db(transaction=True)


class TestConcurrentConfirmPayment:

    def test_only_one_confirm_succeeds(
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

        assert len(results) == 1
        assert len(errors) == 1

        assert successful_payment.is_consumed