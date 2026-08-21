# tests/fixtures/orders.py
import pytest


from decimal import Decimal
from django.utils import timezone
from datetime import timedelta

from tests.factories.order import (
    OrderFactory,
    OrderItemFactory,
    OrderWithItemsFactory,
)
from order.models import (
    OrderModel,
    OrderItemModel,
    SaleType,
    OrderStatusType,
)

from payment.models import (
    PaymentModel,
)
from payment.enums import (
    PaymentStatusType,
)
# @pytest.fixture
# def order(db, user):
#     return OrderFactory(user=user)
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
def paid_order(order):
    order.status = OrderStatusType.paid
    # order.status = OrderFactory(paid=True)
    order.save(update_fields=["status"])
    return order


# @pytest.fixture
# def processing_order():
#     return OrderFactory(processing=True)
@pytest.fixture
def processing_order(order):
    order.status = OrderStatusType.processing
    order.save(update_fields=["status"])
    return order

# @pytest.fixture
# def shipped_order():
#     return OrderFactory(shipped=True)
@pytest.fixture
def shipped_order(processing_order):
    processing_order.status = OrderStatusType.shipped
    processing_order.save(update_fields=["status"])
    return processing_order

# @pytest.fixture
# def delivered_order():
#     return OrderFactory(delivered=True)
@pytest.fixture
def delivered_order(shipped_order):
    shipped_order.status = OrderStatusType.delivered
    shipped_order.save(update_fields=["status"])
    return shipped_order

# @pytest.fixture
# def failed_order():
#     return OrderFactory(failed=True)
@pytest.fixture
def failed_order(order):
    order.status = OrderStatusType.failed
    order.save(update_fields=["status"])
    return order

# @pytest.fixture
# def cancelled_order():
#     return OrderFactory(cancelled=True)
@pytest.fixture
def cancelled_order(order):
    order.status = OrderStatusType.cancelled
    order.save(update_fields=["status"])
    return order

@pytest.fixture
def returned_order():
    return OrderFactory(returned=True)


@pytest.fixture
def return_requested_order():
    return OrderFactory(return_requested=True)


# @pytest.fixture
# def refunded_order():
#     return OrderFactory(refunded=True)
@pytest.fixture
def refunded_order(paid_order):
    paid_order.status = OrderStatusType.refunded
    paid_order.save(update_fields=["status"])
    return paid_order

@pytest.fixture
def order_with_items():
    return OrderWithItemsFactory()

@pytest.fixture
def order_item(db, order):
    return OrderItemFactory(order=order)

@pytest.fixture
def empty_order(
    user,
    address,
):
    """
    Order without any item.
    Useful for validation tests.
    """

    return OrderModel.objects.create(
        user=user,
        sale_type=SaleType.ONLINE,
        status=OrderStatusType.pending,

        total_price=Decimal("0"),

        full_name=user.profile.get_fullname(),
        phone=user.profile.phone_number,
        email=user.email,

        address=address.address,
        city=address.city,
        state=address.state,
        zip_code=address.zip_code,

        expire_at=timezone.now() + timedelta(minutes=15),
    )
    
@pytest.fixture
def second_product(product_factory):
    """
    Independent product.
    Used in inventory/order scenarios.
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
    product,
    second_product,
):
    total = (
        product.final_price
        + second_product.final_price
    )

    order = OrderModel.objects.create(
        user=user,
        sale_type=SaleType.ONLINE,
        status=OrderStatusType.pending,

        total_price=total,

        full_name=user.profile.get_fullname(),
        phone=user.profile.phone_number,
        email=user.email,

        address=address.address,
        city=address.city,
        state=address.state,
        zip_code=address.zip_code,

        expire_at=timezone.now() + timedelta(minutes=15),
    )

    OrderItemModel.objects.bulk_create(
        [
            OrderItemModel(
                order=order,
                product=product,
                quantity=2,
                price=product.final_price,
            ),
            OrderItemModel(
                order=order,
                product=second_product,
                quantity=3,
                price=second_product.final_price,
            ),
        ]
    )

    return order


@pytest.fixture
def paid_order_with_two_products(
    order_with_two_products,
):

    order_with_two_products.status = OrderStatusType.paid

    order_with_two_products.save(
        update_fields=["status"]
    )

    return order_with_two_products


@pytest.fixture
def expired_order(order):

    order.expire_at = timezone.now() - timedelta(minutes=10)

    order.save(update_fields=["expire_at"])

    return order

