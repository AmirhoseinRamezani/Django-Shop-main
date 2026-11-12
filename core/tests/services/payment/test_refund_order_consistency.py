from decimal import Decimal
from unittest.mock import patch

import pytest
from django.db.models import Sum
from django.utils import timezone

from events.models import OutboxEvent, OutboxStatus
from order.events.order_event import OrderEvent, OrderEventType
from order.models import (
    InventoryReservation,
    InventoryReservationStatus,
    OrderStatusType,
)
from order.services.inventory import InventoryService
from order.services.state_machine import OrderStateMachine
from payment.enums import PaymentGateway, PaymentStatusType, RefundStatus
from payment.exceptions import (
    PaymentInvariantViolation,
    PaymentRefundAmountInvalidError,
)
from payment.providers.base import GatewayRefundResult
from payment.services.refund import RefundService
from tests.factories.order import OrderItemFactory
from tests.factories.payment import PaymentAttemptFactory, PaymentFactory
from tests.factories.shop import ProductFactory

pytestmark = pytest.mark.django_db


PAYMENT_AMOUNT = Decimal("1000000")


def make_refundable_payment(*, amount=PAYMENT_AMOUNT):
    payment = PaymentFactory(
        order__status=OrderStatusType.paid,
        order__paid_date=timezone.now(),
        order__total_price=amount,
        order__subtotal_price=amount,
        order__payable_price=amount,
        amount=amount,
        status=PaymentStatusType.SUCCESS,
        is_consumed=True,
        is_refunded=False,
    )
    PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        success=True,
    )
    return payment


def successful_gateway_result(reference: str) -> GatewayRefundResult:
    return GatewayRefundResult(
        success=True,
        gateway=PaymentGateway.ZARINPAL,
        gateway_reference=reference,
        gateway_transaction_id=f"TX-{reference}",
        response_code="100",
        message="Refund successful",
    )


def raise_runtime_error(message: str):
    def _raise(*_args, **_kwargs):
        raise RuntimeError(message)

    return _raise


def refunded_order_events(order_id: int):
    return OrderEvent.objects.filter(
        order_id=order_id,
        type=OrderEventType.REFUNDED,
    )


def refunded_order_outbox_events(order_id: int):
    return OutboxEvent.objects.filter(
        topic="order.refunded",
        payload__order_id=order_id,
    )


class TestRefundOrderConsistency:

    def test_refund_order_rejects_partial_refund_key_reuse(
        self,
        admin_user,
    ):
        payment = make_refundable_payment()

        with patch(
            "payment.services.refund.GatewayService.refund",
            return_value=successful_gateway_result("PARTIAL-KEY-REUSE"),
        ) as gateway:
            partial = RefundService.refund(
                payment_id=payment.pk,
                amount=Decimal("400000"),
                idempotency_key="shared-refund-order-key",
                reason="customer_request",
                actor=admin_user,
            )

            # The partial refund was stored with operation_type="amount".
            # refund_order requests operation_type="full" with the same
            # idempotency key, so the operation-type guard fires before
            # any amount comparison.
            with pytest.raises(
                PaymentInvariantViolation,
                match="different operation type",
            ):
                RefundService.refund_order(
                    order_id=payment.order_id,
                    payment_id=payment.pk,
                    actor=admin_user,
                    idempotency_key="shared-refund-order-key",
                )

        assert partial.status == RefundStatus.SUCCESS
        assert payment.refunds.count() == 1
        gateway.assert_called_once()

    def test_repeated_full_refund_order_request_returns_existing_refund(
        self,
        admin_user,
    ):
        payment = make_refundable_payment()

        with patch(
            "payment.services.refund.GatewayService.refund",
            return_value=successful_gateway_result("FULL-KEY-REPLAY"),
        ) as gateway:
            first = RefundService.refund_order(
                order_id=payment.order_id,
                payment_id=payment.pk,
                actor=admin_user,
                idempotency_key="full-refund-order-replay",
            )
            second = RefundService.refund_order(
                order_id=payment.order_id,
                payment_id=payment.pk,
                actor=admin_user,
                idempotency_key="full-refund-order-replay",
            )

        assert second.pk == first.pk
        assert payment.refunds.count() == 1
        gateway.assert_called_once()

    def test_refund_order_rejects_key_owned_by_another_payment(
        self,
        admin_user,
    ):
        first_payment = make_refundable_payment()
        second_payment = make_refundable_payment()

        with patch(
            "payment.services.refund.GatewayService.refund",
            return_value=successful_gateway_result("CROSS-PAYMENT-KEY"),
        ) as gateway:
            RefundService.refund(
                payment_id=first_payment.pk,
                amount=Decimal("300000"),
                idempotency_key="cross-payment-refund-key",
                reason="customer_request",
                actor=admin_user,
            )

            with pytest.raises(PaymentInvariantViolation):
                RefundService.refund_order(
                    order_id=second_payment.order_id,
                    payment_id=second_payment.pk,
                    actor=admin_user,
                    idempotency_key="cross-payment-refund-key",
                )

        assert first_payment.refunds.count() == 1
        assert second_payment.refunds.count() == 0
        gateway.assert_called_once()

    def test_full_refund_atomically_finalizes_payment_order_event_and_outbox(
        self,
        admin_user,
    ):
        payment = make_refundable_payment()
        order = payment.order
        original_payment_amount = payment.amount

        with patch(
            "payment.services.refund.GatewayService.refund",
            return_value=successful_gateway_result("FULL-REFUND-1"),
        ) as gateway:
            refund = RefundService.refund(
                payment_id=payment.pk,
                amount=payment.amount,
                idempotency_key="refund-order-full-1",
                reason="customer_request",
                actor=admin_user,
            )

        refund.refresh_from_db()
        payment.refresh_from_db()
        order.refresh_from_db()

        successful_total = payment.refunds.filter(
            status=RefundStatus.SUCCESS,
        ).aggregate(total=Sum("amount"))["total"]

        assert gateway.call_count == 1
        assert refund.status == RefundStatus.SUCCESS
        assert payment.amount == original_payment_amount
        assert successful_total == payment.amount
        assert payment.is_refunded is True
        assert payment.is_fully_refunded is True
        assert order.status == OrderStatusType.refunded

        event = refunded_order_events(order.pk).get()
        outbox = refunded_order_outbox_events(order.pk).get()

        assert event.actor_id == admin_user.pk
        assert event.payload["order_id"] == order.pk
        assert event.payload["payment_id"] == payment.pk
        assert event.payload["refunded_amount"] == str(payment.amount)
        assert outbox.payload == event.payload
        assert outbox.status == OutboxStatus.pending

    def test_partial_refunds_preserve_order_until_cumulative_total_is_full(
        self,
        admin_user,
    ):
        payment = make_refundable_payment()
        order = payment.order
        original_payment_amount = payment.amount

        with patch(
            "payment.services.refund.GatewayService.refund",
            side_effect=(
                successful_gateway_result("PARTIAL-REFUND-1"),
                successful_gateway_result("PARTIAL-REFUND-2"),
            ),
        ) as gateway:
            first = RefundService.refund(
                payment_id=payment.pk,
                amount=Decimal("400000"),
                idempotency_key="refund-order-partial-1",
                reason="customer_request",
                actor=admin_user,
            )

            first.refresh_from_db()
            payment.refresh_from_db()
            order.refresh_from_db()

            first_total = payment.refunds.filter(
                status=RefundStatus.SUCCESS,
            ).aggregate(total=Sum("amount"))["total"]

            assert first.status == RefundStatus.SUCCESS
            assert first_total == Decimal("400000")
            assert payment.amount - first_total == Decimal("600000")
            assert payment.is_refunded is False
            assert order.status == OrderStatusType.paid
            assert refunded_order_events(order.pk).count() == 0
            assert refunded_order_outbox_events(order.pk).count() == 0

            second = RefundService.refund(
                payment_id=payment.pk,
                amount=Decimal("600000"),
                idempotency_key="refund-order-partial-2",
                reason="customer_request",
                actor=admin_user,
            )

        first.refresh_from_db()
        second.refresh_from_db()
        payment.refresh_from_db()
        order.refresh_from_db()

        successful_total = payment.refunds.filter(
            status=RefundStatus.SUCCESS,
        ).aggregate(total=Sum("amount"))["total"]

        assert gateway.call_count == 2
        assert first.status == RefundStatus.SUCCESS
        assert second.status == RefundStatus.SUCCESS
        assert payment.amount == original_payment_amount
        assert successful_total == payment.amount
        assert payment.amount - successful_total == Decimal("0")
        assert payment.is_refunded is True
        assert order.status == OrderStatusType.refunded
        assert refunded_order_events(order.pk).count() == 1
        assert refunded_order_outbox_events(order.pk).count() == 1

    @pytest.mark.parametrize("failure_point", ("payment", "event", "outbox"))
    def test_full_refund_finalization_rolls_back_all_local_effects_on_failure(
        self,
        admin_user,
        monkeypatch,
        failure_point,
    ):
        payment = make_refundable_payment()
        order = payment.order

        if failure_point == "payment":
            from payment.repositories.payment_repository import PaymentRepository

            monkeypatch.setattr(
                PaymentRepository,
                "save_refund_state",
                raise_runtime_error("simulated Payment persistence failure"),
            )
        elif failure_point == "event":
            monkeypatch.setattr(
                "order.services.state_machine.record_order_event",
                raise_runtime_error("simulated domain event persistence failure"),
            )
        else:
            monkeypatch.setattr(
                "order.services.events.OutboxEvent.objects.create",
                raise_runtime_error("simulated Outbox persistence failure"),
            )

        with patch(
            "payment.services.refund.GatewayService.refund",
            return_value=successful_gateway_result(
                f"ROLLBACK-{failure_point.upper()}"
            ),
        ):
            with pytest.raises(RuntimeError):
                RefundService.refund(
                    payment_id=payment.pk,
                    amount=payment.amount,
                    idempotency_key=f"refund-order-rollback-{failure_point}",
                    reason="customer_request",
                    actor=admin_user,
                )

        payment.refresh_from_db()
        order.refresh_from_db()
        refund = payment.refunds.get(
            idempotency_key=f"refund-order-rollback-{failure_point}",
        )

        assert refund.status == RefundStatus.PENDING
        assert refund.finished_at is None
        assert payment.is_refunded is False
        assert order.status == OrderStatusType.paid
        assert refunded_order_events(order.pk).count() == 0
        assert refunded_order_outbox_events(order.pk).count() == 0

    def test_full_refund_does_not_revive_an_order_that_left_refundable_state(
        self,
        admin_user,
    ):
        payment = make_refundable_payment()
        order = payment.order

        def gateway_refund_then_advance_order(**_kwargs):
            # Simulate the valid paid -> processing transition while Gateway
            # HTTP is in flight and no database lock is held by RefundService.
            from order.services.state_machine import OrderStateMachine

            OrderStateMachine.transition(
                order=order,
                to_status=OrderStatusType.processing,
                actor=admin_user,
            )
            OrderStateMachine.transition(
                order=order,
                to_status=OrderStatusType.shipped,
                actor=admin_user,
            )

            return successful_gateway_result("ORDER-ADVANCED-1")

        with patch(
            "payment.services.refund.GatewayService.refund",
            side_effect=gateway_refund_then_advance_order,
        ):
            with pytest.raises(
                PaymentInvariantViolation,
                match="current lifecycle state",
            ):
                RefundService.refund(
                    payment_id=payment.pk,
                    amount=payment.amount,
                    idempotency_key="refund-order-invalid-transition-1",
                    reason="customer_request",
                    actor=admin_user,
                )

        payment.refresh_from_db()
        order.refresh_from_db()
        refund = payment.refunds.get(
            idempotency_key="refund-order-invalid-transition-1",
        )

        assert refund.status == RefundStatus.PENDING
        assert payment.is_refunded is False
        assert order.status == OrderStatusType.shipped
        assert refunded_order_events(order.pk).count() == 0
        assert refunded_order_outbox_events(order.pk).count() == 0


    def test_processing_order_remains_processing_until_cumulative_full_refund(
        self,
        admin_user,
    ):
        payment = make_refundable_payment()
        order = payment.order
        OrderStateMachine.transition(
            order=order,
            to_status=OrderStatusType.processing,
        )

        product = ProductFactory(stock=10)
        item = OrderItemFactory(
            order=order,
            product=product,
            quantity=2,
        )
        InventoryService.reserve(order)
        InventoryService.consume(order)
        product.refresh_from_db()
        stock_after_consumption = product.stock
        reservation = InventoryReservation.objects.get(order_item=item)
        original_payment_amount = payment.amount

        with patch(
            "payment.services.refund.GatewayService.refund",
            side_effect=[
                successful_gateway_result("PROCESSING-PARTIAL-1"),
                successful_gateway_result("PROCESSING-PARTIAL-2"),
            ],
        ) as gateway:
            first = RefundService.refund(
                payment_id=payment.pk,
                amount=Decimal("400000"),
                idempotency_key="processing-partial-1",
                reason="customer_request",
                actor=admin_user,
            )

            order.refresh_from_db()
            payment.refresh_from_db()
            product.refresh_from_db()
            reservation.refresh_from_db()

            assert first.status == RefundStatus.SUCCESS
            assert order.status == OrderStatusType.processing
            assert payment.is_refunded is False
            assert payment.amount == original_payment_amount
            assert reservation.status == InventoryReservationStatus.CONSUMED
            assert product.stock == stock_after_consumption
            assert refunded_order_events(order.pk).count() == 0
            assert refunded_order_outbox_events(order.pk).count() == 0

            second = RefundService.refund(
                payment_id=payment.pk,
                amount=Decimal("600000"),
                idempotency_key="processing-partial-2",
                reason="customer_request",
                actor=admin_user,
            )

        order.refresh_from_db()
        payment.refresh_from_db()
        product.refresh_from_db()
        reservation.refresh_from_db()

        assert second.status == RefundStatus.SUCCESS
        assert order.status == OrderStatusType.refunded
        assert payment.is_refunded is True
        assert payment.amount == original_payment_amount
        assert reservation.status == InventoryReservationStatus.CONSUMED
        assert reservation.released_at is None
        assert product.stock == stock_after_consumption
        assert refunded_order_events(order.pk).count() == 1
        assert refunded_order_outbox_events(order.pk).count() == 1
        assert gateway.call_count == 2