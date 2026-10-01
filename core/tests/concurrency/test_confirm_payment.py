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
   
def test_cancel_and_confirm_are_mutually_exclusive(
    order,
    successful_payment,
):
    """Order locking makes cancellation and payment confirmation mutually exclusive."""

    from django.db import close_old_connections
    from django.core.exceptions import ValidationError

    from order.services.state_machine import OrderStateMachine
    from tests.concurrency.base import ConcurrentRunner

    outcomes = []
    errors = []
    lock = threading.Lock()

    def confirm():
        try:
            confirm_order_payment(order.id)
            with lock:
                outcomes.append("confirmed")
        except ValidationError:
            with lock:
                outcomes.append("rejected")
        except BaseException as exc:
            with lock:
                errors.append(exc)

    def cancel():
        try:
            OrderStateMachine.transition(
                order=order,
                to_status=OrderStatusType.cancelled,
            )
            with lock:
                outcomes.append("cancelled")
        except ValidationError:
            with lock:
                outcomes.append("rejected")
        except BaseException as exc:
            with lock:
                errors.append(exc)

    try:
        ConcurrentRunner().run(confirm, cancel)
    finally:
        close_old_connections()

    order.refresh_from_db()
    successful_payment.refresh_from_db()

    assert errors == []
    assert len(outcomes) == 2
    assert outcomes.count("rejected") == 1
    assert {outcome for outcome in outcomes if outcome != "rejected"} in ({"confirmed"}, {"cancelled"})

    if order.status == OrderStatusType.paid:
        assert successful_payment.is_consumed is True
    else:
        assert order.status == OrderStatusType.cancelled
        assert successful_payment.is_consumed is False
    