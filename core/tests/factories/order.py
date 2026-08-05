# tests/factories/order.py
from datetime import timedelta

import factory
from factory import fuzzy
from django.utils import timezone

from tests.base import BaseFactory

from order.models import (
    OrderModel,
    OrderItemModel,
    SaleType,
    OrderStatusType,
)

from tests.factories.accounts import UserFactory

from tests.factories.shop import (
    AddressFactory,
    CouponFactory,
    ProductFactory,
)


class OrderFactory(BaseFactory):

    class Meta:
        model = OrderModel

    user = factory.SubFactory(UserFactory)

    sale_type = SaleType.ONLINE

    status = OrderStatusType.pending

    total_price = fuzzy.FuzzyInteger(100000, 5000000)

    # full_name = factory.Faker("name")
    full_name = factory.LazyAttribute(
        lambda o: o.user.profile.get_fullname()
    )

    # phone = '09123456789'
    phone = factory.LazyAttribute(
        lambda o: o.user.profile.phone_number
    )

    email = factory.LazyAttribute(
        lambda o: o.user.email
    )

    address = "Test Address"

    city = "Tehran"

    state = "Tehran"

    zip_code = "1111111111"

    coupon = None

    coupon_code = None

    coupon_discount_percent = None

    expire_at = factory.LazyFunction(
        lambda: timezone.now() + timedelta(minutes=15)
    )

    class Params:

        failed = factory.Trait(
            status=OrderStatusType.failed,
        )

        paid = factory.Trait(
            status=OrderStatusType.paid,
        )

        processing = factory.Trait(
            status=OrderStatusType.processing,
        )

        shipped = factory.Trait(
            status=OrderStatusType.shipped,
        )

        delivered = factory.Trait(
            status=OrderStatusType.delivered,
        )

        return_requested = factory.Trait(
            status=OrderStatusType.return_requested,
        )

        returned = factory.Trait(
            status=OrderStatusType.returned,
        )

        refunded = factory.Trait(
            status=OrderStatusType.refunded,
        )

        cancelled = factory.Trait(
            status=OrderStatusType.cancelled,
        )

        with_coupon = factory.Trait(
            coupon=factory.SubFactory(CouponFactory),

            coupon_code=factory.SelfAttribute(
                "..coupon.code"
            ),

            coupon_discount_percent=factory.SelfAttribute(
                "..coupon.discount_percent"
            ),
        )

        expired = factory.Trait(
            expire_at=factory.LazyFunction(
                lambda: timezone.now() - timedelta(minutes=10)
            )
        )

        payable = factory.Trait(
            expire_at=factory.LazyFunction(
                lambda: timezone.now() + timedelta(minutes=15)
            )
        )


class OrderItemFactory(BaseFactory):

    class Meta:
        model = OrderItemModel

    order = factory.SubFactory(OrderFactory)

    product = factory.SubFactory(ProductFactory)

    quantity = fuzzy.FuzzyInteger(1, 5)

    price = factory.LazyAttribute(
        lambda o: o.product.final_price
    )


class OrderWithItemsFactory(OrderFactory):

    @factory.post_generation
    def items(self, create, extracted, **kwargs):

        if not create:
            return

        count = extracted or 2

        for _ in range(count):

            OrderItemFactory(order=self)


# CouponFactory
# AddressFactory
# OrderFactory
# OrderItemFactory