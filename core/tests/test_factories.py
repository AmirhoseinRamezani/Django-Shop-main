# tests/test_factories.py

from decimal import Decimal

import pytest
from django.utils import timezone

from payment.enums import (
    Currency,
    GatewayLogDirection,
    GatewayLogType,
    PaymentAttemptStatus,
    PaymentGateway,
    PaymentStatusType,
    RefundStatus,
)

from events.models import OutboxStatus

from payment.models import (
    GatewayLog,
    PaymentAttempt,
    PaymentModel,
    Refund,
)

from order.models import (
    OrderItemModel,
    OrderModel,
    OrderStatusType,
)

from shop.models import (
    ProductStatusType,
)

from tests.factories.accounts import (
    UserFactory,
    ProfileFactory,
    DeviceSessionFactory,
    RefreshTokenFactory,
)

from tests.factories.events import (
    OutboxEventFactory,
)

from tests.factories.payment import (
    PaymentFactory,
    PaymentAttemptFactory,
    GatewayLogFactory,
    RefundFactory,
)

from tests.factories.shop import (
    AddressFactory,
    CouponFactory,
    ProductFactory,
    ProductCategoryFactory,
)

from tests.factories.order import (
    OrderFactory,
    OrderItemFactory,
    OrderWithItemsFactory,
)


pytestmark = pytest.mark.django_db


# ================================
# ACCOUNTS FACTORIES
# ================================


class TestAccountFactories:

    def test_user_factory(self):

        user = UserFactory()

        assert user.pk is not None
        assert user.email.startswith("user")
        assert user.is_active is True
        assert user.is_verified is True

        assert user.profile.pk is not None

    def test_user_factory_profile_override(self):

        user = UserFactory(
            profile={
                "first_name": "Ali",
                "last_name": "Ahmadi",
                "phone_number": "09123456789",
            }
        )

        profile = user.profile

        assert profile.pk is not None
        assert profile.first_name == "Ali"
        assert profile.last_name == "Ahmadi"
        assert profile.phone_number == "09123456789"

    def test_user_admin_trait(self):

        user = UserFactory(admin=True)

        assert user.is_staff is True
        assert user.is_superuser is False

    def test_user_superuser_trait(self):

        user = UserFactory(superuser=True)

        assert user.is_staff is True
        assert user.is_superuser is True

    def test_user_unverified_trait(self):

        user = UserFactory(unverified=True)

        assert user.is_verified is False

    def test_profile_factory(self):

        profile = ProfileFactory()

        assert profile.pk is not None
        assert profile.user_id is not None
        assert profile.first_name
        assert profile.last_name
        assert profile.phone_number

    def test_device_session_factory(self):

        session = DeviceSessionFactory()

        assert session.pk is not None
        assert session.user_id is not None
        assert session.device_hash
        assert session.ip_address == "127.0.0.1"

    def test_refresh_token_factory(self):

        token = RefreshTokenFactory()

        assert token.pk is not None
        assert token.user_id is not None
        assert token.session_id is not None
        assert token.token


# ================================
# SHOP FACTORIES
# ================================


class TestShopFactories:

    def test_product_category_factory(self):

        category = ProductCategoryFactory()

        assert category.pk is not None
        assert category.title
        assert category.slug

    def test_product_factory(self):

        product = ProductFactory()

        assert product.pk is not None
        assert product.status == ProductStatusType.PUBLISH
        assert product.stock == 10
        assert product.reserved_stock == 0
        assert product.discount_percent == 0
        assert product.sku
        assert product.barcode

        assert product.category.exists()

    def test_product_factory_draft(self):

        product = ProductFactory(draft=True)

        assert product.status == ProductStatusType.DRAFT

    def test_product_factory_unpublished(self):

        product = ProductFactory(unpublished=True)

        assert product.status == ProductStatusType.DRAFT

    def test_product_factory_out_of_stock(self):

        product = ProductFactory(out_of_stock=True)

        assert product.stock == 0
        assert product.reserved_stock == 0

    def test_product_factory_discounted(self):

        product = ProductFactory(discounted=True)

        assert product.discount_percent == 20

    def test_product_category_override(self):

        category = ProductCategoryFactory()

        product = ProductFactory(
            category=[category],
        )

        assert product.category.filter(pk=category.pk).exists()

    def test_coupon_factory(self):

        coupon = CouponFactory()

        assert coupon.pk is not None
        assert coupon.code
        assert coupon.is_active is True
        assert coupon.used_count == 0
        assert coupon.max_limit_usage == 10

    def test_coupon_expired(self):

        coupon = CouponFactory(expired=True)

        assert coupon.expiration_date < timezone.now()
        assert coupon.is_valid() is False

    def test_coupon_inactive(self):

        coupon = CouponFactory(inactive=True)

        assert coupon.is_active is False
        assert coupon.is_valid() is False

    def test_coupon_exhausted(self):

        coupon = CouponFactory(exhausted=True)

        assert coupon.used_count == coupon.max_limit_usage
        assert coupon.is_valid() is False

    def test_address_factory(self):

        address = AddressFactory()

        assert address.pk is not None
        assert address.user_id is not None
        assert address.city == "Mashhad"
        assert address.state == "Khorasan"
        assert address.zip_code == "9187654321"


# ================================
# CART FACTORIES
# ================================


class TestCartFactories:

    def test_cart_factory(self):

        from tests.factories.cart import CartFactory

        cart = CartFactory()

        assert cart.pk is not None
        assert cart.user_id is not None

    def test_cart_item_factory(self):

        from tests.factories.cart import CartItemFactory

        item = CartItemFactory()

        assert item.pk is not None
        assert item.cart_id is not None
        assert item.product_id is not None
        assert item.quantity == 1

    def test_cart_item_two_trait(self):

        from tests.factories.cart import CartItemFactory

        item = CartItemFactory(two=True)

        assert item.quantity == 2

    def test_cart_item_many_trait(self):

        from tests.factories.cart import CartItemFactory

        item = CartItemFactory(many=True)

        assert item.quantity == 5


# ================================
# ORDER FACTORIES
# ================================


class TestOrderFactories:

    def test_order_factory(self):

        order = OrderFactory()

        assert order.pk is not None
        assert order.user_id is not None

        assert order.status == OrderStatusType.pending
        assert order.sale_type

        assert order.total_price == Decimal("100000")
        assert order.subtotal_price == Decimal("100000")
        assert order.discount_amount == Decimal("0")
        assert order.shipping_price == Decimal("0")
        assert order.tax_amount == Decimal("0")
        assert order.payable_price == Decimal("100000")

        assert order.paid_date is None
        assert order.completed_date is None
        assert order.cancelled_date is None

        assert order.is_payable is True

    def test_order_paid(self):

        order = OrderFactory(paid=True)

        assert order.status == OrderStatusType.paid
        assert order.paid_date is not None
        assert order.is_paid is True

    def test_order_processing(self):

        order = OrderFactory(processing=True)

        assert order.status == OrderStatusType.processing
        assert order.paid_date is not None
        assert order.is_paid is True

    def test_order_shipped(self):

        order = OrderFactory(shipped=True)

        assert order.status == OrderStatusType.shipped
        assert order.paid_date is not None
        assert order.is_paid is True

    def test_order_delivered(self):

        order = OrderFactory(delivered=True)

        assert order.status == OrderStatusType.delivered
        assert order.paid_date is not None
        assert order.completed_date is not None
        assert order.is_paid is True
        assert order.is_completed is True

    def test_order_return_requested(self):

        order = OrderFactory(return_requested=True)

        assert order.status == OrderStatusType.return_requested
        assert order.paid_date is not None
        assert order.is_paid is True

    def test_order_returned(self):

        order = OrderFactory(returned=True)

        assert order.status == OrderStatusType.returned
        assert order.paid_date is not None
        assert order.is_paid is True

    def test_order_refunded(self):

        order = OrderFactory(refunded=True)

        assert order.status == OrderStatusType.refunded
        assert order.paid_date is not None
        assert order.is_paid is True
        assert order.is_completed is True

    def test_order_failed(self):

        order = OrderFactory(failed=True)

        assert order.status == OrderStatusType.failed
        assert order.paid_date is None
        assert order.is_paid is False

    def test_order_cancelled(self):

        order = OrderFactory(cancelled=True)

        assert order.status == OrderStatusType.cancelled
        assert order.cancelled_date is not None
        assert order.paid_date is None
        assert order.is_completed is True

    def test_order_expired(self):

        order = OrderFactory(expired=True)

        assert order.expire_at < timezone.now()
        assert order.is_expired() is True
        assert order.is_payable is False

    def test_order_payable(self):

        order = OrderFactory(payable=True)

        assert order.expire_at > timezone.now()
        assert order.status == OrderStatusType.pending
        assert order.is_payable is True

    def test_order_with_coupon(self):

        order = OrderFactory(with_coupon=True)

        assert order.coupon_id is not None
        assert order.coupon_code == order.coupon.code
        assert (
            order.coupon_discount_percent
            == order.coupon.discount_percent
        )

    def test_order_item_factory(self):

        item = OrderItemFactory()

        assert item.pk is not None
        assert item.order_id is not None
        assert item.product_id is not None

        assert item.quantity >= 1
        assert item.price == item.product.final_price

    def test_order_with_items_factory(self):

        order = OrderWithItemsFactory(items=2)

        assert order.pk is not None

        items = order.order_items.all()

        assert items.count() == 2

        for item in items:
            assert item.order_id == order.pk
            assert item.product_id is not None
            assert item.quantity >= 1
            assert item.price == item.product.final_price


# ================================
# PAYMENT FACTORIES
# ================================


class TestPaymentFactories:

    def test_payment_factory(self):

        payment = PaymentFactory()

        assert payment.pk is not None
        assert payment.order_id is not None

        assert payment.amount > 0
        assert payment.currency == Currency.IRR
        assert payment.gateway == PaymentGateway.ZARINPAL
        assert payment.status == PaymentStatusType.PENDING

        assert payment.version == 1
        assert payment.is_consumed is False
        assert payment.is_refunded is False

    def test_payment_success(self):

        payment = PaymentFactory(success=True)

        assert payment.status == PaymentStatusType.SUCCESS
        assert payment.is_successful is True
        assert payment.is_consumed is False

    def test_payment_failed(self):

        payment = PaymentFactory(failed=True)

        assert payment.status == PaymentStatusType.FAILED
        assert payment.is_failed is True

    def test_payment_consumed(self):

        payment = PaymentFactory(consumed=True)

        assert payment.status == PaymentStatusType.SUCCESS
        assert payment.is_consumed is True
        assert payment.is_refunded is False
        assert payment.can_consume is False
        assert payment.can_refund is True

    def test_payment_refunded(self):

        payment = PaymentFactory(refunded=True)

        assert payment.status == PaymentStatusType.SUCCESS
        assert payment.is_consumed is True
        assert payment.is_refunded is True
        assert payment.is_fully_refunded is True
        assert payment.can_refund is False


# ================================
# PAYMENT ATTEMPT FACTORIES
# ================================


class TestPaymentAttemptFactories:

    def test_payment_attempt_pending(self):

        attempt = PaymentAttemptFactory()

        assert attempt.pk is not None
        assert attempt.payment_id is not None

        assert attempt.attempt_number == 1
        assert attempt.retry_count == 1

        assert attempt.status == PaymentAttemptStatus.PENDING

        assert attempt.gateway_reference == ""
        assert attempt.gateway_transaction_id == ""

        assert attempt.finished_at is None

        assert attempt.is_pending is True
        assert attempt.is_terminal is False

    def test_payment_attempt_success(self):

        attempt = PaymentAttemptFactory(success=True)

        assert attempt.status == PaymentAttemptStatus.SUCCESS

        assert attempt.authority_id
        assert attempt.gateway_reference
        assert attempt.gateway_transaction_id

        assert attempt.response_code == "100"
        assert attempt.gateway_message == "Payment successful"

        assert attempt.finished_at is not None
        assert attempt.latency_ms == 120

        assert attempt.is_success is True
        assert attempt.is_terminal is True
        assert attempt.is_finished is True

    def test_payment_attempt_failed(self):

        attempt = PaymentAttemptFactory(failed=True)

        assert attempt.status == PaymentAttemptStatus.FAILED

        assert attempt.failure_reason == "Gateway payment failed"
        assert attempt.response_code == "-1"
        assert attempt.gateway_message == "Payment failed"

        assert attempt.finished_at is not None
        assert attempt.latency_ms == 250

        assert attempt.is_failed is True
        assert attempt.is_terminal is True
        assert attempt.is_finished is True

    def test_payment_attempt_timeout(self):

        attempt = PaymentAttemptFactory(timeout=True)

        assert attempt.status == PaymentAttemptStatus.TIMEOUT

        assert attempt.failure_reason == "Gateway timeout"
        assert attempt.finished_at is not None
        assert attempt.latency_ms == 5000

        assert attempt.is_timeout is True
        assert attempt.is_terminal is True
        assert attempt.is_finished is True

    def test_payment_attempt_cancelled(self):

        attempt = PaymentAttemptFactory(cancelled=True)

        assert attempt.status == PaymentAttemptStatus.CANCELLED

        assert attempt.failure_reason == "Payment attempt cancelled"
        assert attempt.finished_at is not None
        assert attempt.latency_ms == 100

        assert attempt.is_cancelled is True
        assert attempt.is_terminal is True
        assert attempt.is_finished is True

    def test_payment_attempt_belongs_to_payment(self):

        attempt = PaymentAttemptFactory()

        assert attempt.payment.pk == attempt.payment_id

    def test_payment_attempt_external_reference(self):

        attempt = PaymentAttemptFactory(success=True)

        assert (
            attempt.external_reference
            == attempt.gateway_transaction_id
        )


# ================================
# REFUND FACTORIES
# ================================


class TestRefundFactories:

    def test_refund_factory(self):

        refund = RefundFactory()

        assert refund.pk is not None
        assert refund.payment_id is not None

        assert refund.amount == refund.payment.amount
        assert refund.currency == refund.payment.currency

        assert refund.idempotency_key
        assert refund.reason
        
        assert refund.status == RefundStatus.PENDING

        assert refund.requested_at is not None
        assert refund.finished_at is None

        assert refund.is_pending is True
        assert refund.is_terminal is False
        assert refund.is_finished is False

    def test_refund_success(self):

        refund = RefundFactory(success=True)

        assert refund.status == RefundStatus.SUCCESS

        assert refund.finished_at is not None
        assert refund.finished_at >= refund.requested_at

        assert refund.gateway_reference
        assert refund.gateway_transaction_id == ""
        assert refund.failure_reason == ""

        assert refund.is_success is True
        assert refund.is_terminal is True
        assert refund.is_finished is True
        
        assert refund.external_reference == refund.gateway_reference

    def test_refund_failed(self):

        refund = RefundFactory(
            failed=True,
        )

        assert refund.status == RefundStatus.FAILED

        assert refund.failure_reason == "Gateway refund failed"

        assert refund.finished_at is not None
        assert refund.finished_at >= refund.requested_at

        assert refund.is_failed is True
        assert refund.is_terminal is True
        assert refund.is_finished is True


# ================================
# GATEWAY LOG FACTORIES
# ================================


class TestGatewayLogFactories:

    def test_gateway_log_for_payment_attempt(self):

        attempt = PaymentAttemptFactory()

        log = GatewayLogFactory(
            attempt=attempt,
            refund=None,
            gateway=PaymentGateway.ZARINPAL,
            log_type=GatewayLogType.REQUEST,
            direction=GatewayLogDirection.OUTBOUND,
        )

        assert log.pk is not None

        assert log.attempt_id == attempt.pk
        assert log.refund_id is None

        assert log.gateway == PaymentGateway.ZARINPAL
        assert log.log_type == GatewayLogType.REQUEST
        assert log.direction == GatewayLogDirection.OUTBOUND

        assert log.request_method == "POST"
        assert log.http_status == 200
        assert log.latency_ms == 120

        assert log.is_success is True

    def test_gateway_log_for_refund(self):

        refund = RefundFactory()

        log = GatewayLogFactory(
            attempt=None,
            refund=refund,
            gateway=PaymentGateway.ZARINPAL,
            log_type=GatewayLogType.REFUND,
            direction=GatewayLogDirection.OUTBOUND,
        )

        assert log.pk is not None

        assert log.attempt_id is None
        assert log.refund_id == refund.pk

        assert log.gateway == PaymentGateway.ZARINPAL
        assert log.log_type == GatewayLogType.REFUND
        assert log.direction == GatewayLogDirection.OUTBOUND

    def test_gateway_log_request_payload(self):

        attempt = PaymentAttemptFactory()

        log = GatewayLogFactory(
            attempt=attempt,
            refund=None,
            gateway=PaymentGateway.ZARINPAL,
            log_type=GatewayLogType.REQUEST,
            direction=GatewayLogDirection.OUTBOUND,
            request_payload={
                "amount": "100000",
                "currency": "IRR",
            },
        )

        assert log.request_payload["amount"] == "100000"
        assert log.request_payload["currency"] == "IRR"


# ================================
# EVENTS FACTORIES
# ================================


class TestEventFactories:

    def test_outbox_event_factory(self):

        event = OutboxEventFactory()

        assert event.pk is not None
        assert event.topic
        assert event.payload
        assert event.status

        assert event.retry_count == 0
        assert event.last_error is None

    def test_outbox_processed(self):

        event = OutboxEventFactory(processed=True)

        assert event.status == OutboxStatus.processed

    def test_outbox_failed(self):

        event = OutboxEventFactory(failed=True)

        assert event.retry_count == 3
        assert event.last_error == "Gateway timeout"

    def test_outbox_retryable(self):

        event = OutboxEventFactory(retryable=True)

        assert event.retry_count == 1


# ================================
# RELATIONSHIP TESTS
# ================================


class TestFactoryRelationships:

    def test_user_profile_relationship(self):

        user = UserFactory()

        assert user.profile.user_id == user.pk

    def test_product_category_relationship(self):

        product = ProductFactory()

        assert product.category.exists()

    def test_order_user_relationship(self):

        order = OrderFactory()

        assert order.user_id == order.user.pk

    def test_order_coupon_relationship(self):

        order = OrderFactory(with_coupon=True)

        assert order.coupon_id == order.coupon.pk

    def test_order_item_relationship(self):

        item = OrderItemFactory()

        assert item.order_id == item.order.pk
        assert item.product_id == item.product.pk

    def test_payment_order_relationship(self):

        payment = PaymentFactory()

        assert payment.order_id == payment.order.pk

    def test_payment_attempt_payment_relationship(self):

        attempt = PaymentAttemptFactory()

        assert attempt.payment_id == attempt.payment.pk

    def test_payment_attempt_gateway_log_relationship(self):

        attempt = PaymentAttemptFactory()

        log = GatewayLogFactory(
            attempt=attempt,
            refund=None,
            gateway=PaymentGateway.ZARINPAL,
            log_type=GatewayLogType.REQUEST,
            direction=GatewayLogDirection.OUTBOUND,
        )

        assert log.attempt_id == attempt.pk
        assert log.attempt == attempt

    def test_refund_payment_relationship(self):

        refund = RefundFactory()

        assert refund.payment_id == refund.payment.pk

    def test_refund_gateway_log_relationship(self):

        refund = RefundFactory()

        log = GatewayLogFactory(
            attempt=None,
            refund=refund,
            gateway=PaymentGateway.ZARINPAL,
            log_type=GatewayLogType.REFUND,
            direction=GatewayLogDirection.OUTBOUND,
        )

        assert log.refund_id == refund.pk
        assert log.refund == refund