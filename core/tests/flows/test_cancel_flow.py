# tests/flows/test_cancel_flow.py
import pytest

from django.core.exceptions import ValidationError

from order.models import OrderStatusType

from order.services.order import OrderService
from order.services.state_machine import OrderStateMachine

pytestmark = pytest.mark.django_db


class TestCancelFlow:

    def test_cancel_pending_order(
        self,
        user,
        address,
        cart,
        product,
    ):
        """
        pending -> cancelled
        stock restored
        """

        initial_stock = product.stock

        cart.add(product, quantity=2)

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        product.refresh_from_db()

        assert product.stock == initial_stock - 2

        OrderStateMachine.transition(
            order=order,
            to_status=OrderStatusType.cancelled,
            actor=user,
        )

        order.refresh_from_db()
        product.refresh_from_db()

        assert order.status == OrderStatusType.cancelled
        assert product.stock == initial_stock

    def test_cannot_cancel_paid_order(
        self,
        paid_order,
        user,
    ):

        with pytest.raises(ValidationError):

            OrderStateMachine.transition(
                order=paid_order,
                to_status=OrderStatusType.cancelled,
                actor=user,
            )

    def test_cancel_twice(
        self,
        cancelled_order,
        user,
    ):

        with pytest.raises(ValidationError):

            OrderStateMachine.transition(
                order=cancelled_order,
                to_status=OrderStatusType.cancelled,
                actor=user,
            )

    def test_cancel_restores_every_item(
        self,
        user,
        address,
        cart,
        product_factory,
    ):

        p1 = product_factory(stock=20)
        p2 = product_factory(stock=15)

        stock1 = p1.stock
        stock2 = p2.stock

        cart.add(p1, quantity=3)
        cart.add(p2, quantity=5)

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        OrderStateMachine.transition(
            order=order,
            to_status=OrderStatusType.cancelled,
        )

        p1.refresh_from_db()
        p2.refresh_from_db()

        assert p1.stock == stock1
        assert p2.stock == stock2

    def test_event_recorded(
        self,
        user,
        address,
        cart,
        product,
        mocker,
    ):

        event = mocker.patch(
            "order.services.state_machine.record_order_event"
        )

        cart.add(product)

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        OrderStateMachine.transition(
            order=order,
            to_status=OrderStatusType.cancelled,
            actor=user,
        )

        assert event.call_count == 2

    def test_timeout_cancel(
        self,
        pending_order,
    ):

        OrderStateMachine.transition(
            order=pending_order,
            to_status=OrderStatusType.cancelled,
            payload={
                "reason": "timeout"
            },
        )

        pending_order.refresh_from_db()

        assert pending_order.status == OrderStatusType.cancelled

    def test_inventory_restore_called(
        self,
        pending_order,
        mocker,
    ):

        restore = mocker.patch(
            "order.services.state_machine.InventoryService.restore"
        )

        OrderStateMachine.transition(
            order=pending_order,
            to_status=OrderStatusType.cancelled,
        )

        restore.assert_called_once()

    def test_only_pending_restores_inventory(
        self,
        processing_order,
        mocker,
    ):

        restore = mocker.patch(
            "order.services.state_machine.InventoryService.restore"
        )

        with pytest.raises(ValidationError):

            OrderStateMachine.transition(
                order=processing_order,
                to_status=OrderStatusType.cancelled,
            )

        restore.assert_not_called()

    def test_cancel_is_atomic(
        self,
        pending_order,
        mocker,
    ):

        mocker.patch(
            "order.services.state_machine.record_order_event",
            side_effect=RuntimeError(),
        )

        with pytest.raises(RuntimeError):

            OrderStateMachine.transition(
                order=pending_order,
                to_status=OrderStatusType.cancelled,
            )

        pending_order.refresh_from_db()

        assert pending_order.status == OrderStatusType.pending

    def test_actor_saved(
        self,
        pending_order,
        user,
        mocker,
    ):

        event = mocker.patch(
            "order.services.state_machine.record_order_event"
        )

        OrderStateMachine.transition(
            order=pending_order,
            to_status=OrderStatusType.cancelled,
            actor=user,
        )

        kwargs = event.call_args.kwargs

        assert kwargs["actor"] == user

    def test_payload_saved(
        self,
        pending_order,
        mocker,
    ):

        event = mocker.patch(
            "order.services.state_machine.record_order_event"
        )

        OrderStateMachine.transition(
            order=pending_order,
            to_status=OrderStatusType.cancelled,
            payload={
                "reason": "customer"
            },
        )

        kwargs = event.call_args.kwargs

        assert kwargs["payload"]["reason"] == "customer"
        
"""
This file covers almost all Cancel scenarios

Test coverage:

✅ happy path
✅ inventory restore
✅ multi item
✅ illegal transition
✅ timeout cancellation
✅ event generation
✅ actor
✅ payload
✅ rollback
✅ idempotency
✅ side effect"""
        
        