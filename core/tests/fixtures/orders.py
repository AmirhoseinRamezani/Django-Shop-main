# tests/fixtures/orders.py
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from django.utils import timezone

from order.models import (
    OrderItemModel,
    OrderModel,
    OrderStatusType,
    SaleType,
)

from tests.factories.order import (
    OrderFactory,
    OrderItemFactory,
    OrderWithItemsFactory,
)
from tests.factories.shop import CouponFactory


# ============================================================
# BASIC ORDERS
# ============================================================


@pytest.fixture
def order(
    user,
    address,
    product,
):
    """
    Standard pending order.
    """

    order = OrderModel.objects.create(
        user=user,
        sale_type=SaleType.ONLINE,
        status=OrderStatusType.pending,

        total_price=product.final_price,

        subtotal_price=product.final_price,
        discount_amount=Decimal("0"),
        shipping_price=Decimal("0"),
        tax_amount=Decimal("0"),
        payable_price=product.final_price,

        full_name=user.profile.get_fullname(),
        phone=user.profile.phone_number,
        email=user.email,

        address=address.address,
        city=address.city,
        state=address.state,
        zip_code=address.zip_code,

        expire_at=timezone.now() + timedelta(minutes=15),
    )

    OrderItemModel.objects.create(
        order=order,
        product=product,
        quantity=1,
        price=product.final_price,
    )

    return order


@pytest.fixture
def pending_order(order):
    return order


@pytest.fixture
def expired_order(
    order,
):
    """
    Pending order whose expiration time is in the past.

    This fixture intentionally preserves the pending-order
    lifecycle invariant and only changes expire_at.
    """

    order.expire_at = (
        timezone.now() - timedelta(minutes=1)
    )

    order.save(
        update_fields=[
            "expire_at",
        ],
    )

    return order


# ============================================================
# COUPON ORDER
# ============================================================


@pytest.fixture
def order_with_coupon(
    order,
    coupon,
):
    """
    Attach a valid coupon to the existing standard order.

    Important:
        This fixture mutates the same `order` fixture instead
        of creating another Order.

    This guarantees that:

        order_with_coupon
            and
        success_payment

    refer to the same Order when used together in a test.
    """

    order.coupon = coupon
    order.coupon_code = coupon.code
    order.coupon_discount_percent = coupon.discount_percent

    order.save(
        update_fields=[
            "coupon",
            "coupon_code",
            "coupon_discount_percent",
        ],
    )

    return order


# ============================================================
# ORDER STATES
# ============================================================


@pytest.fixture
def paid_order(order):
    """
    Valid PAID order fixture.

    paid_date is mandatory for paid-like statuses.
    """

    order.status = OrderStatusType.paid
    order.paid_date = timezone.now()

    order.save(
        update_fields=[
            "status",
            "paid_date",
        ],
    )

    return order


@pytest.fixture
def processing_order(order):
    """
    Valid PROCESSING order fixture.
    """

    order.status = OrderStatusType.processing
    order.paid_date = timezone.now()

    order.save(
        update_fields=[
            "status",
            "paid_date",
        ],
    )

    return order


@pytest.fixture
def shipped_order(processing_order):
    processing_order.status = OrderStatusType.shipped

    processing_order.save(
        update_fields=[
            "status",
        ],
    )

    return processing_order


@pytest.fixture
def delivered_order(shipped_order):
    shipped_order.status = OrderStatusType.delivered
    shipped_order.completed_date = timezone.now()

    shipped_order.save(
        update_fields=[
            "status",
            "completed_date",
        ],
    )

    return shipped_order


@pytest.fixture
def failed_order(order):
    order.status = OrderStatusType.failed

    order.save(
        update_fields=[
            "status",
        ],
    )

    return order


@pytest.fixture
def cancelled_order(order):
    order.status = OrderStatusType.cancelled
    order.cancelled_date = timezone.now()

    order.save(
        update_fields=[
            "status",
            "cancelled_date",
        ],
    )

    return order


@pytest.fixture
def returned_order():
    """
    Factory owns the complete returned-state invariant.
    """

    return OrderFactory(
        returned=True,
    )


@pytest.fixture
def return_requested_order():
    """
    Factory owns the complete return-requested-state invariant.
    """

    return OrderFactory(
        return_requested=True,
    )


@pytest.fixture
def refunded_order(paid_order):
    """
    PAID -> REFUNDED.

    paid_date remains populated.
    """

    paid_order.status = OrderStatusType.refunded

    paid_order.save(
        update_fields=[
            "status",
        ],
    )

    return paid_order


# ============================================================
# ITEMS
# ============================================================


@pytest.fixture
def order_with_items():
    return OrderWithItemsFactory()


@pytest.fixture
def order_item(
    db,
    order,
):
    return OrderItemFactory(
        order=order,
    )


@pytest.fixture
def empty_order(
    user,
    address,
):
    """
    Order without any item.
    """

    return OrderModel.objects.create(
        user=user,
        sale_type=SaleType.ONLINE,
        status=OrderStatusType.pending,

        total_price=Decimal("0"),

        subtotal_price=Decimal("0"),
        discount_amount=Decimal("0"),
        shipping_price=Decimal("0"),
        tax_amount=Decimal("0"),
        payable_price=Decimal("0"),

        full_name=user.profile.get_fullname(),
        phone=user.profile.phone_number,
        email=user.email,

        address=address.address,
        city=address.city,
        state=address.state,
        zip_code=address.zip_code,

        expire_at=timezone.now() + timedelta(minutes=15),
    )


# ============================================================
# MULTI-PRODUCT ORDERS
# ============================================================


@pytest.fixture
def second_product(product_factory):
    """
    Independent product.
    """

    return product_factory(
        title="Second Product",
        stock=20,
        final_price=Decimal("250000"),
    )


@pytest.fixture
def order_with_two_products(
    user,
    address,
    product_factory,
):
    """
    Order containing two independent products.
    """

    product_1 = product_factory(
        title="Product One",
        stock=20,
        final_price=Decimal("100000"),
    )

    product_2 = product_factory(
        title="Product Two",
        stock=20,
        final_price=Decimal("200000"),
    )

    total_price = (
        product_1.final_price
        + product_2.final_price
    )

    order = OrderModel.objects.create(
        user=user,
        sale_type=SaleType.ONLINE,
        status=OrderStatusType.pending,

        total_price=total_price,

        subtotal_price=total_price,
        discount_amount=Decimal("0"),
        shipping_price=Decimal("0"),
        tax_amount=Decimal("0"),
        payable_price=total_price,

        full_name=user.profile.get_fullname(),
        phone=user.profile.phone_number,
        email=user.email,

        address=address.address,
        city=address.city,
        state=address.state,
        zip_code=address.zip_code,

        expire_at=timezone.now() + timedelta(minutes=15),
    )

    OrderItemModel.objects.create(
        order=order,
        product=product_1,
        quantity=1,
        price=product_1.final_price,
    )

    OrderItemModel.objects.create(
        order=order,
        product=product_2,
        quantity=1,
        price=product_2.final_price,
    )

    return order