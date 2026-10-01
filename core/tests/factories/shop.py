# tests/factories/shop.py
import factory
from decimal import Decimal

from django.utils import timezone
from datetime import timedelta

from tests.factories.base import BaseFactory

from shop.models import (
    ProductModel,
    ProductCategoryModel,

)

from shop.constants import (
    ProductStatusType,
)

from order.models import (
    CouponModel,
    UserAddressModel,
)

from tests.factories.accounts import UserFactory

# from tests.factories.shop import ProductCategoryFactory
# from tests.factories.shop import (
#     ProductFactory,
#     CouponFactory,
#     AddressFactory,
#     ProductCategoryFactory
# )
class ProductCategoryFactory(BaseFactory):
    class Meta:
        model = ProductCategoryModel

    title = factory.Sequence(lambda n: f"Category {n}")
    slug = factory.Sequence(lambda n: f"category-{n}")

class ProductFactory(BaseFactory):

    class Meta:
        model = ProductModel
        skip_postgeneration_save = True

    user = factory.SubFactory(UserFactory)
    
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
    avg_rate = 0

    sku = factory.Sequence(
        lambda n: f"SKU-{n:08d}"
    )

    barcode = factory.Sequence(
        lambda n: f"BARCODE-{n:012d}"
    )
    
    reserved_stock = 0
    
    description = factory.Faker(
        "paragraph"
    )

    brief_description = factory.Faker(
        "sentence"
    )
    # is_active = True

    @factory.post_generation
    def category(self, create, extracted, **kwargs):

        if not create:
            return

        categories = extracted

        if categories:
            for category in categories:
                self.category.add(category)
            return

        self.category.add(
            ProductCategoryFactory()
        )

    class Params:

        draft = factory.Trait(
            status=ProductStatusType.DRAFT,
        )

        unpublished = factory.Trait(
            status=ProductStatusType.DRAFT,
        )
        
        out_of_stock = factory.Trait(
            stock=0,
            reserved_stock=0,
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

    state = "Khorasan"
    city = "Mashhad"
    address = "Some Street"
    zip_code = "9187654321"


# CategoryFactory
# ProductFactory
# WishlistFactory
# ProductImageFactory