# tests/factories/shop.py
import factory
from decimal import Decimal
from django.utils import timezone
from datetime import timedelta

from tests.base import BaseFactory

from shop.models import (
    ProductModel,
)

from shop.constants import (
    ProductStatusType,
)

from order.models import (
    CouponModel,
    UserAddressModel,
)
from tests.factories.accounts import UserFactory


class ProductFactory(BaseFactory):

    class Meta:
        model = ProductModel

    # category = factory.SubFactory(CategoryFactory)

    title = factory.Sequence(
        lambda n: f"Product {n}"
    )

    slug = factory.Sequence(
        lambda n: f"product-{n}"
    )

    price = Decimal("100000")

    discount_percent = 0

    stock = 10

    status = ProductStatusType.PUBLISH

    is_active = True

    class Params:

        draft = factory.Trait(
            status=ProductStatusType.DRAFT,
        )

        out_of_stock = factory.Trait(
            stock=0,
        )

        discounted = factory.Trait(
            discount_percent=20,
        )


class CouponFactory(BaseFactory):

    class Meta:
        model = CouponModel

    code = factory.Sequence(
        lambda n: f"OFF{100+n}"
    )

    discount_percent = 10

    max_limit_usage = 10

    used_count = 0

    expiration_date = factory.LazyFunction(
        lambda: timezone.now() + timedelta(days=7)
    )

    is_active = True

    class Params:

        expired = factory.Trait(
            expiration_date=factory.LazyFunction(
                lambda: timezone.now() - timedelta(days=1)
            )
        )

        inactive = factory.Trait(
            is_active=False,
        )

        exhausted = factory.Trait(
            used_count=10,
            max_limit_usage=10,
        )


class AddressFactory(BaseFactory):

    class Meta:
        model = UserAddressModel

    user = factory.SubFactory(UserFactory)

    address = factory.Faker("address")

    city = "Tehran"

    state = "Tehran"

    zip_code = "1111111111"
    
# CategoryFactory
# ProductFactory
# WishlistFactory
# ProductImageFactory