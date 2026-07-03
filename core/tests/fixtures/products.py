import pytest

# from decimal import Decimal

# from shop.models import (
#     ProductModel,
#     ProductCategoryModel,
# )

# @pytest.fixture
# def category():

#     return ProductCategoryModel.objects.create(
#         title="Laptop",
#         slug="laptop",
#     )

from tests.factories.shop import (
    ProductFactory,
    CouponFactory,
    AddressFactory,
)

@pytest.fixture
def product(db):
    return ProductFactory()


@pytest.fixture
def published_product(db):
    return ProductFactory()


@pytest.fixture
def draft_product(db):
    return ProductFactory(draft=True)


@pytest.fixture
def out_of_stock_product(db):
    return ProductFactory(out_of_stock=True)


@pytest.fixture
def coupon(db):
    return CouponFactory()


@pytest.fixture
def expired_coupon(db):
    return CouponFactory(expired=True)


@pytest.fixture
def address(db, user):
    return AddressFactory(user=user)
