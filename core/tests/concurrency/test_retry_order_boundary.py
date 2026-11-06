from __future__ import annotations

import threading
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.db import close_old_connections, connections, connection
from django.utils import timezone

from order.events.order_event import OrderEventType
from order.models import OrderStatusType
from order.services.state_machine import OrderStateMachine
from payment.enums import PaymentAttemptStatus, PaymentGateway, PaymentStatusType
from payment.exceptions import PaymentInitiationForbiddenError
from payment.providers.base import GatewayPaymentResult
from payment.services.retry import RetryPaymentService
from tests.factories.order import OrderFactory
from tests.factories.payment import PaymentAttemptFactory, PaymentFactory


pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="Concurrency correctness requires PostgreSQL row locks.",
    ),
]


@pytest.mark.parametrize("order_change", ("cancel", "expire"))
@pytest.mark.parametrize("order_change_wins", (True, False))
def test_retry_gateway_initiation_serializes_with_order_lifecycle(
    order_change: str,
    order_change_wins: bool,
):
    order = OrderFactory()
    payment = PaymentFactory(order=order)
    PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        failed=True,
    )

    gateway_entered = threading.Event()
    release_gateway = threading.Event()
    worker_finished = threading.Event()
    worker_results: list[str] = []
    worker_errors: list[BaseException] = []

    authority = f"AUTH-RETRY-{order_change.upper()}-RACE"
    payment_url = f"https://gateway.test/pay/{authority}"

    def initiate_gateway(*args, **kwargs):
        gateway_entered.set()
        if not release_gateway.wait(timeout=15):
            raise AssertionError("Gateway barrier was not released.")
        return GatewayPaymentResult(
            success=True,
            gateway=PaymentGateway.ZARINPAL,
            authority=authority,
            response_code="100",
            message="accepted",
        )

    def payment_worker():
        close_old_connections()
        try:
            worker_results.append(
                RetryPaymentService.retry(
                    order=order,
                    callback_url="https://shop.test/payment/verify/",
                )
            )
        except BaseException as exc:
            worker_errors.append(exc)
        finally:
            connections.close_all()
            worker_finished.set()

    def change_order():
        if order_change == "cancel":
            OrderStateMachine.transition(
                order=order,
                to_status=OrderStatusType.cancelled,
                payload={"reason": "customer-cancel"},
            )
            return

        order.expire_at = timezone.now() - timedelta(seconds=1)
        order.save(update_fields=("expire_at",))
        call_command("expire_pending_orders")

    with (
        patch(
            "payment.services.retry.GatewayService.initiate_payment",
            side_effect=initiate_gateway,
        ),
        patch(
            "payment.services.retry.GatewayService.payment_url",
            return_value=payment_url,
        ) as mocked_payment_url,
    ):
        worker = threading.Thread(target=payment_worker)
        worker.start()

        assert gateway_entered.wait(timeout=15), (
            "Retry did not reach Gateway I/O."
        )

        if order_change_wins:
            change_order()
            release_gateway.set()
        else:
            release_gateway.set()
            assert worker_finished.wait(timeout=15), (
                "Retry initiation did not finish."
            )
            change_order()

        worker.join(timeout=20)

    assert not worker.is_alive()
    assert worker_finished.is_set()

    if order_change_wins:
        assert worker_results == []
        assert len(worker_errors) == 1
        assert isinstance(
            worker_errors[0],
            PaymentInitiationForbiddenError,
        )
        mocked_payment_url.assert_not_called()
    else:
        assert worker_errors == []
        assert worker_results == [payment_url]
        mocked_payment_url.assert_called_once()

    order.refresh_from_db()
    payment.refresh_from_db()
    retry_attempt = payment.attempts.get(attempt_number=2)

    if order_change == "cancel":
        assert order.status == OrderStatusType.cancelled
    else:
        assert order.status == OrderStatusType.pending
        assert order.is_expired()

    assert payment.status == PaymentStatusType.PENDING
    assert payment.is_consumed is False
    assert retry_attempt.status == PaymentAttemptStatus.PENDING
    assert retry_attempt.authority_id == authority
    assert not order.events.filter(type=OrderEventType.PAID).exists()