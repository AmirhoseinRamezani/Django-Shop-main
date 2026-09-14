# tests/integration/test_checkout_flow.py
import pytest

from order.models import OrderStatusType
from order.services.order import OrderService
from payment.enums import PaymentGateway, PaymentStatusType
from payment.providers.base import GatewayPaymentResult, GatewayVerificationResult
from payment.services.services import PaymentService
from payment.services.verify import verify_payment

from tests.assertions import (
    refresh,
    assert_order_paid,
    assert_payment_success,
)

pytestmark = pytest.mark.django_db


def _mock_gateway(mocker, authority="AUTH-123"):
    mocker.patch(
        "payment.services.services.GatewayService.initiate_payment",
        return_value=GatewayPaymentResult(
            success=True,
            gateway=PaymentGateway.ZARINPAL,
            authority=authority,
        ),
    )
    mocker.patch(
        "payment.services.services.GatewayService.payment_url",
        side_effect=lambda value, gateway=None: f"https://gateway/{value}",
    )


def _mock_verification(mocker, payment, reference="REF-1234"):
    mocker.patch(
        "payment.services.verify.GatewayService.verify",
        return_value=GatewayVerificationResult(
            success=True,
            gateway=PaymentGateway.ZARINPAL,
            gateway_reference=reference,
            gateway_transaction_id="TXN-1234",
            response_code="100",
            message="verified",
            amount=payment.amount,
            currency=payment.currency,
        ),
    )


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
        _mock_gateway(mocker)

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        url = PaymentService.start_payment(order)
        payment = order.payments.get()
        attempt = payment.attempts.get()
        _mock_verification(mocker, payment)

        verify_payment(
            payment_id=payment.pk,
            attempt_id=attempt.pk,
            ref_id="REF-1234",
            response={},
        )

        refresh(order, payment)

        assert url.endswith(attempt.authority_id)
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
        _mock_gateway(mocker, authority="AUTH-COUPON")

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
            coupon=coupon,
        )

        PaymentService.start_payment(order)
        payment = order.payments.get()
        attempt = payment.attempts.get()
        _mock_verification(mocker, payment, reference="REF-COUPON")

        verify_payment(
            payment_id=payment.pk,
            attempt_id=attempt.pk,
            ref_id="REF-COUPON",
        )

        refresh(order, payment, coupon)

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
        _mock_gateway(mocker, authority="AUTH-TWICE")

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        PaymentService.start_payment(order)
        payment = order.payments.get()
        attempt = payment.attempts.get()
        _mock_verification(mocker, payment, reference="REF-TWICE")

        verify_payment(
            payment_id=payment.pk,
            attempt_id=attempt.pk,
            ref_id="REF-TWICE",
        )

        payment.refresh_from_db()
        assert payment.status == PaymentStatusType.success

        second = verify_payment(
            payment_id=payment.pk,
            attempt_id=attempt.pk,
            ref_id="REF-TWICE",
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
        _mock_gateway(mocker, authority="AUTH-STOCK")

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        product.refresh_from_db()
        assert product.stock == initial_stock - 3

        PaymentService.start_payment(order)
        payment = order.payments.get()
        attempt = payment.attempts.get()
        _mock_verification(mocker, payment, reference="REF-STOCK")

        verify_payment(
            payment_id=payment.pk,
            attempt_id=attempt.pk,
            ref_id="REF-STOCK",
        )

        product.refresh_from_db()
        assert product.stock == initial_stock - 3
