# test/services/order/test_state_machine
import pytest

from django.core.exceptions import ValidationError

from order.models import OrderStatusType
from order.services.state_machine import OrderStateMachine

from tests.assertions import (
    assert_stock_restored,
    refresh,
)

pytestmark = pytest.mark.django_db


class TestOrderStateMachine:

    def test_pending_to_paid(
        self,
        order,
    ):
        OrderStateMachine.transition(
            order=order,
            to_status=OrderStatusType.paid,
        )

        refresh(order)

        assert order.status == OrderStatusType.paid

    def test_pending_to_cancelled(
        self,
        order_builder,
        product,
    ):
        old_stock = product.stock

        order = (
            order_builder
            .with_item(product, 2)
            .build()
        )

        product.stock -= 2
        product.save()

        OrderStateMachine.transition(
            order=order,
            to_status=OrderStatusType.cancelled,
        )

        refresh(
            order,
            product,
        )

        assert order.status == OrderStatusType.cancelled

        assert_stock_restored(
            product,
            old_stock,
        )

    def test_illegal_transition(
        self,
        order,
    ):
        with pytest.raises(ValidationError):

            OrderStateMachine.transition(
                order=order,
                to_status=OrderStatusType.shipped,
            )

    def test_paid_to_processing(
        self,
        paid_order,
    ):
        OrderStateMachine.transition(
            order=paid_order,
            to_status=OrderStatusType.processing,
        )

        refresh(paid_order)

        assert (
            paid_order.status
            == OrderStatusType.processing
        )

    def test_processing_to_shipped(
        self,
        processing_order,
    ):
        OrderStateMachine.transition(
            order=processing_order,
            to_status=OrderStatusType.shipped,
        )

        refresh(processing_order)

        assert (
            processing_order.status
            == OrderStatusType.shipped
        )

    def test_return_flow(
        self,
        processing_order,
    ):
        OrderStateMachine.transition(
            order=processing_order,
            to_status=OrderStatusType.shipped,
        )

        OrderStateMachine.transition(
            order=processing_order,
            to_status=OrderStatusType.return_requested,
        )

        OrderStateMachine.transition(
            order=processing_order,
            to_status=OrderStatusType.returned,
        )

        OrderStateMachine.transition(
            order=processing_order,
            to_status=OrderStatusType.refunded,
        )

        refresh(processing_order)

        assert (
            processing_order.status
            == OrderStatusType.refunded
        )