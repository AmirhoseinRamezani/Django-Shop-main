# tests/factories/order.py
from datetime import timedelta
from decimal import Decimal

import factory
from factory import fuzzy
from django.utils import timezone

from tests.factories.base import BaseFactory

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

    # total_price = factory.Faker("pydecimal", left_digits=5, right_digits=2, positive=True)
    # Legacy gross total kept because it is still a real model field.
    total_price = Decimal("100000")

    # Pricing snapshot
    subtotal_price = Decimal("100000")
    discount_amount = Decimal("0")
    shipping_price = Decimal("0")
    tax_amount = Decimal("0")
    payable_price = Decimal("100000")

    # Buyer snapshot
    full_name = factory.LazyAttribute(
        lambda o: o.user.profile.get_fullname()
    )


    phone = factory.LazyAttribute(
        lambda o: o.user.profile.phone_number
    )

    email = factory.LazyAttribute(
        lambda o: o.user.email
    )

    # Address snapshot
    address = "Test Address"
    city = "Tehran"
    state = "Tehran"
    zip_code = "1111111111"
    coupon = None
    coupon_code = None
    coupon_discount_percent = None
    
    # Datetime fields (Constraint enforcement)
    paid_date = None
    completed_date = None
    cancelled_date = None

    expire_at = factory.LazyFunction(
        lambda: timezone.now() + timedelta(minutes=15)
    )

    class Params:

        failed = factory.Trait(
            status=OrderStatusType.failed,
            # paid_date=factory.LazyFunction(timezone.now),
        )

        paid = factory.Trait(
            status=OrderStatusType.paid,
            paid_date=factory.LazyFunction(timezone.now),
        )

        processing = factory.Trait(
            status=OrderStatusType.processing,
            paid_date=factory.LazyFunction(timezone.now),
        )

        shipped = factory.Trait(
            status=OrderStatusType.shipped,
            paid_date=factory.LazyFunction(timezone.now),
        )

        delivered = factory.Trait(
            status=OrderStatusType.delivered,
            paid_date=factory.LazyFunction(timezone.now),
            completed_date=factory.LazyFunction(timezone.now),
        )

        return_requested = factory.Trait(
            status=OrderStatusType.return_requested,
            paid_date=factory.LazyFunction(timezone.now),
        )

        returned = factory.Trait(
            status=OrderStatusType.returned,
            paid_date=factory.LazyFunction(timezone.now),
        )

        refunded = factory.Trait(
            status=OrderStatusType.refunded,
            paid_date=factory.LazyFunction(timezone.now),
        )

        cancelled = factory.Trait(
            status=OrderStatusType.cancelled,
            paid_date=None,
            cancelled_date=factory.LazyFunction(timezone.now),
        )

        with_coupon = factory.Trait(
            coupon=factory.SubFactory(CouponFactory),

            coupon_code=factory.SelfAttribute(
                "coupon.code"
            ),

            coupon_discount_percent=factory.SelfAttribute(
                "coupon.discount_percent"
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
    
    class Meta:
        skip_postgeneration_save = True
        
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