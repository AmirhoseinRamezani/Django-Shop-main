from __future__ import annotations

import threading
from unittest.mock import patch

import pytest
from django.db import close_old_connections, connections, connection

from order.events.order_event import OrderEventType
from order.models import (
    CouponReservation,
    CouponReservationStatus,
    OrderStatusType,
)
from order.services.coupon import CouponService
from order.services.state_machine import OrderStateMachine
from payment.enums import (
    PaymentAttemptStatus,
    PaymentGateway,
    PaymentStatusType,
)
from payment.exceptions import PaymentInitiationForbiddenError
from payment.models import (
    PaymentResolution,
    PaymentResolutionReason,
    PaymentResolutionStatus,
)
from payment.providers.base import (
    GatewayInquiryResult,
    GatewayPaymentResult,
)
from payment.services.reconciliation import PaymentReconciliationService
from payment.services.services import PaymentService
from tests.factories.order import OrderFactory
from tests.factories.shop import CouponFactory


pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="Concurrency correctness requires PostgreSQL row locks.",
    ),
]


@pytest.mark.parametrize(
    "cancellation_wins",
    (True, False),
    ids=("cancellation-wins", "initiation-wins"),
)
def test_order_cancellation_races_with_gateway_initiation(
    cancellation_wins: bool,
):
    coupon = CouponFactory(max_limit_usage=1)
    order = OrderFactory(
        coupon=coupon,
        coupon_code=coupon.code,
        coupon_discount_percent=coupon.discount_percent,
    )
    CouponService.reserve_for_order(order)

    gateway_entered = threading.Event()
    release_gateway = threading.Event()
    worker_finished = threading.Event()

    worker_results: list[str] = []
    worker_errors: list[BaseException] = []

    authority = "AUTH-CANCEL-INITIATION-RACE"
    payment_url = "https://gateway.test/pay/AUTH-CANCEL-INITIATION-RACE"

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
            result = PaymentService.start_payment(
                order,
                callback_url="https://shop.test/payment/verify/",
            )
            worker_results.append(result)
        except BaseException as exc:
            worker_errors.append(exc)
        finally:
            connections.close_all()
            worker_finished.set()

    worker = threading.Thread(target=payment_worker)

    with (
        patch(
            "payment.services.services.GatewayService.current_gateway",
            return_value=PaymentGateway.ZARINPAL,
        ),
        patch(
            "payment.services.services.GatewayService.initiate_payment",
            side_effect=initiate_gateway,
        ),
        patch(
            "payment.services.services.GatewayService.payment_url",
            return_value=payment_url,
        ),
    ):
        worker.start()

        assert gateway_entered.wait(timeout=15), (
            "Payment initiation did not reach Gateway I/O."
        )

        if cancellation_wins:
            OrderStateMachine.transition(
                order=order,
                to_status=OrderStatusType.cancelled,
                payload={"reason": "customer-cancel"},
            )
            release_gateway.set()
        else:
            release_gateway.set()
            assert worker_finished.wait(timeout=15), (
                "Payment initiation did not finish."
            )
            OrderStateMachine.transition(
                order=order,
                to_status=OrderStatusType.cancelled,
                payload={"reason": "customer-cancel"},
            )

        worker.join(timeout=15)

    assert not worker.is_alive(), "Payment worker did not terminate."
    assert worker_finished.is_set()

    if cancellation_wins:
        assert worker_results == []
        assert len(worker_errors) == 1
        assert isinstance(
            worker_errors[0],
            PaymentInitiationForbiddenError,
        )
    else:
        assert worker_errors == []
        assert worker_results == [payment_url]

    order.refresh_from_db()
    payment = order.payments.get()
    attempt = payment.attempts.get()

    assert order.status == OrderStatusType.cancelled
    assert payment.status == PaymentStatusType.PENDING
    assert payment.is_consumed is False
    assert attempt.status == PaymentAttemptStatus.PENDING
    assert attempt.authority_id == authority
    assert not order.events.filter(type=OrderEventType.PAID).exists()

    # Cancellation must retain the coupon reservation while the Payment
    # outcome remains unresolved.
    coupon.refresh_from_db()
    reservation = CouponReservation.objects.get(order=order)

    assert coupon.reserved_count == 1
    assert coupon.used_count == 0
    assert reservation.status == CouponReservationStatus.RESERVED

    # The persisted authority must remain usable by reconciliation.
    with patch(
        "payment.services.reconciliation.GatewayService.inquire",
        return_value=GatewayInquiryResult(
            success=True,
            gateway=PaymentGateway.ZARINPAL,
            gateway_reference="REF-CANCEL-INITIATION-RACE",
            gateway_transaction_id="TX-CANCEL-INITIATION-RACE",
            response_code="100",
            message="verified",
            amount=payment.amount,
            currency=payment.currency,
        ),
    ):
        reconciled_payment = PaymentReconciliationService.reconcile_payment(
            payment_id=payment.pk,
            attempt_id=attempt.pk,
        )

    order.refresh_from_db()
    reconciled_payment.refresh_from_db()
    attempt.refresh_from_db()
    coupon.refresh_from_db()
    reservation.refresh_from_db()

    assert reconciled_payment.status == PaymentStatusType.SUCCESS
    assert reconciled_payment.is_consumed is False
    assert attempt.status == PaymentAttemptStatus.SUCCESS
    assert order.status == OrderStatusType.cancelled
    assert not order.events.filter(type=OrderEventType.PAID).exists()

    resolution = PaymentResolution.objects.get(payment=reconciled_payment)
    assert resolution.status == PaymentResolutionStatus.OPEN
    assert resolution.reason == PaymentResolutionReason.ORDER_CANCELLED
    assert resolution.attempt_id == attempt.pk

    assert coupon.reserved_count == 1
    assert coupon.used_count == 0
    assert reservation.status == CouponReservationStatus.RESERVED