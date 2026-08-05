# tests/integration/test_checkout_flow.py
import pytest

from order.models import OrderStatusType
from payment.models import PaymentStatusType

from order.services.order import OrderService
from payment.services.services import PaymentService
from payment.services.verify import verify_payment

from tests.assertions import (
    refresh,
    assert_order_paid,
    assert_payment_success,
)

pytestmark = pytest.mark.django_db


class DummyGateway:

    def payment_request(self, amount):
        return {
            "Authority": "AUTH-123",
        }

    def generate_payment_url(self, authority):
        return f"https://gateway/{authority}"


class TestCheckoutFlow:

    def test_full_checkout_flow(
        self,
        mocker,
        user,
        address,
        cart_builder,
        product,
    ):
        cart = (
            cart_builder
            .for_user(user)
            .with_item(product, quantity=2)
            .build()
        )

        gateway = mocker.patch(
            "payment.services.services.ZarinPalSandbox"
        )

        gateway.return_value = DummyGateway()

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        url = PaymentService.start_payment(order)

        payment = order.payments.get()

        verify_payment(
            authority=payment.authority_id,
            ref_id=1234,
            response={},
        )

        refresh(order, payment)

        assert url.endswith(payment.authority_id)

        assert_order_paid(order)

        assert_payment_success(payment)

        assert payment.is_consumed

    def test_checkout_with_coupon(
        self,
        mocker,
        user,
        address,
        coupon,
        cart_builder,
        product,
    ):
        cart = (
            cart_builder
            .for_user(user)
            .with_item(product)
            .build()
        )

        gateway = mocker.patch(
            "payment.services.services.ZarinPalSandbox"
        )

        gateway.return_value = DummyGateway()

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
            coupon=coupon,
        )

        PaymentService.start_payment(order)

        payment = order.payments.get()

        verify_payment(
            authority=payment.authority_id,
            ref_id=1234,
        )

        refresh(
            order,
            payment,
            coupon,
        )

        assert coupon.used_count == 1

        assert order.status == OrderStatusType.paid

    def test_payment_cannot_be_verified_twice(
        self,
        mocker,
        user,
        address,
        cart_builder,
        product,
    ):
        cart = (
            cart_builder
            .for_user(user)
            .with_item(product)
            .build()
        )

        gateway = mocker.patch(
            "payment.services.services.ZarinPalSandbox"
        )

        gateway.return_value = DummyGateway()

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        PaymentService.start_payment(order)

        payment = order.payments.get()

        verify_payment(
            authority=payment.authority_id,
            ref_id=1234,
        )

        payment.refresh_from_db()

        assert payment.status == PaymentStatusType.success

        second = verify_payment(
            authority=payment.authority_id,
            ref_id=1234,
        )

        assert second.pk == payment.pk

    def test_stock_reserved_until_payment(
        self,
        mocker,
        user,
        address,
        cart_builder,
        product,
    ):
        initial_stock = product.stock

        cart = (
            cart_builder
            .for_user(user)
            .with_item(product, quantity=3)
            .build()
        )

        gateway = mocker.patch(
            "payment.services.services.ZarinPalSandbox"
        )

        gateway.return_value = DummyGateway()

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        product.refresh_from_db()

        assert product.stock == initial_stock - 3

        PaymentService.start_payment(order)

        payment = order.payments.get()

        verify_payment(
            authority=payment.authority_id,
            ref_id=1234,
        )

        product.refresh_from_db()

        assert product.stock == initial_stock - 3