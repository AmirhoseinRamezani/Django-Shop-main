# tests/concurrency/test_cancel_confirm_race.py
from __future__ import annotations

import queue
import threading

import pytest
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections

from order.models import (
    InventoryReservation,
    InventoryReservationStatus,
    OrderStatusType,
)
from order.services.confirm_payment import (
    OrderFinalizationConflict,
    confirm_order_payment,
)
from order.services.inventory import InventoryService
from order.services.state_machine import OrderStateMachine
from payment.enums import PaymentAttemptStatus, PaymentStatusType
from payment.policies import PaymentPolicy
from tests.factories.order import OrderFactory, OrderItemFactory
from tests.factories.payment import PaymentAttemptFactory, PaymentFactory
from tests.factories.shop import CouponFactory, ProductFactory
from order.models import CouponReservation, CouponReservationStatus
from order.services.coupon import CouponService


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("winner", ("cancel", "confirm"))
def test_cancellation_and_confirmation_serialize_on_order_lock(
    winner,
    monkeypatch,
):
    """Either lifecycle transition may win, but their side effects cannot mix."""
    coupon = CouponFactory(max_limit_usage=1)
    order = OrderFactory(
        coupon=coupon,
        coupon_code=coupon.code,
        coupon_discount_percent=coupon.discount_percent,
    )
    CouponService.reserve_for_order(order)
    product = ProductFactory(stock=5)
    item = OrderItemFactory(
        order=order,
        product=product,
        quantity=2,
        price=product.final_price,
    )
    InventoryService.reserve(order)

    payment = PaymentFactory(order=order, success=True)
    attempt = PaymentAttemptFactory(payment=payment, success=True)

    product.refresh_from_db()
    stock_after_reservation = product.stock
    assert stock_after_reservation == 3

    winner_holds_order_lock = threading.Event()
    release_winner = threading.Event()
    loser_started = threading.Event()
    outcomes: queue.Queue[tuple[str, object]] = queue.Queue()

    def pause_winner() -> None:
        winner_holds_order_lock.set()
        if not release_winner.wait(timeout=10):
            raise AssertionError("test did not release the winning transaction")

    if winner == "cancel":
        original_unresolved_check = CouponService.has_unresolved_payment_outcome

        def paused_unresolved_check(locked_order):
            # StateMachine.transition already locked the Order row before
            # deciding whether unresolved provider evidence permits release.
            pause_winner()
            return original_unresolved_check(locked_order)

        monkeypatch.setattr(
            CouponService,
            "has_unresolved_payment_outcome",
            staticmethod(paused_unresolved_check),
        )
    else:
        original_validate = PaymentPolicy.validate_order_financial_snapshot

        def paused_validate(locked_payment, locked_order):
            # Confirmation has locked the Order and exact Payment rows before
            # financial snapshot validation. Hold that transaction so cancel
            # must wait on the same Order row.
            pause_winner()
            return original_validate(locked_payment, locked_order)

        monkeypatch.setattr(
            PaymentPolicy,
            "validate_order_financial_snapshot",
            staticmethod(paused_validate),
        )

    def run_confirmation() -> None:
        close_old_connections()
        try:
            if winner != "confirm":
                loser_started.set()
            result = confirm_order_payment(order.pk, payment.pk)
            outcomes.put(("confirm", result))
        except BaseException as exc:
            outcomes.put(("confirm", exc))
        finally:
            connections.close_all()

    def run_cancellation() -> None:
        close_old_connections()
        try:
            if winner != "cancel":
                loser_started.set()
            result = OrderStateMachine.transition(
                order=order,
                to_status=OrderStatusType.cancelled,
                payload={"reason": "customer-cancel"},
            )
            outcomes.put(("cancel", result))
        except BaseException as exc:
            outcomes.put(("cancel", exc))
        finally:
            connections.close_all()

    winner_target, loser_target = (
        (run_cancellation, run_confirmation)
        if winner == "cancel"
        else (run_confirmation, run_cancellation)
    )
    winner_thread = threading.Thread(
        target=winner_target,
        name=f"{winner}-order-transition-winner",
    )
    loser_thread = threading.Thread(
        target=loser_target,
        name=f"{winner}-order-transition-loser",
    )

    winner_thread.start()
    try:
        assert winner_holds_order_lock.wait(timeout=10), (
            f"{winner} did not reach the synchronized lock-held point"
        )
        loser_thread.start()
        assert loser_started.wait(timeout=10), "loser worker did not start"
    finally:
        release_winner.set()

    winner_thread.join(timeout=20)
    if loser_thread.ident is not None:
        loser_thread.join(timeout=20)

    assert not winner_thread.is_alive(), "winner worker did not finish"
    assert not loser_thread.is_alive(), "loser worker did not finish"

    results = dict(outcomes.get_nowait() for _ in range(2))
    assert set(results) == {"confirm", "cancel"}

    order.refresh_from_db()
    payment.refresh_from_db()
    attempt.refresh_from_db()
    product.refresh_from_db()
    reservation = InventoryReservation.objects.get(order_item=item)
    coupon_reservation = CouponReservation.objects.get(order=order)
    coupon.refresh_from_db()

    if winner == "confirm":
        assert not isinstance(results["confirm"], BaseException)
        assert isinstance(results["cancel"], ValidationError)
        assert order.status == OrderStatusType.paid
        assert order.paid_date is not None
        assert order.cancelled_date is None
        assert payment.status == PaymentStatusType.SUCCESS
        assert payment.is_consumed is True
        assert attempt.status == PaymentAttemptStatus.SUCCESS
        assert reservation.status == InventoryReservationStatus.RESERVED
        assert product.stock == stock_after_reservation
        assert coupon_reservation.status == CouponReservationStatus.CONSUMED
        assert coupon.used_count == 1
        assert coupon.reserved_count == 0
    else:
        assert isinstance(results["confirm"], OrderFinalizationConflict)
        assert not isinstance(results["cancel"], BaseException)
        assert order.status == OrderStatusType.cancelled
        assert order.cancelled_date is not None
        assert order.paid_date is None
        assert payment.status == PaymentStatusType.SUCCESS
        assert payment.is_consumed is False
        assert attempt.status == PaymentAttemptStatus.SUCCESS
        # Provider success is already persisted but has not been canonically
        # consumed. Cancellation must retain inventory and coupon capacity.
        assert reservation.status == InventoryReservationStatus.RESERVED
        assert product.stock == stock_after_reservation
        assert coupon_reservation.status == CouponReservationStatus.RESERVED
        assert coupon.used_count == 0
        assert coupon.reserved_count == 1
