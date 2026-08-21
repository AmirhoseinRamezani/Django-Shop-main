# tests/test_factories.py
import pytest
from django.db import transaction
from django.utils import timezone

from payment.enums import (
    PaymentStatusType,
)
from order.models import OrderStatusType
from shop.models import ProductStatusType

# from factory.django import DjangoModelFactory
# from tests.factories.base import BaseFactory 

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
)

from tests.factories.shop import (
    AddressFactory,
    CouponFactory,
    ProductFactory,
    ProductCategoryFactory,
)
from tests.factories.order import (
    OrderFactory,
)

pytestmark = pytest.mark.django_db

class TestFactories: #(BaseFactory)

    def test_user_factory(self):

        user = UserFactory()

        assert user.pk
        assert user.profile.pk

    # @pytest.mark.django_db
    def test_profile_factory(self ,**kwargs):

        user = UserFactory(
            profile={
                "first_name": "Ali",
                "last_name": "Ahmadi",
                "phone_number": "09123456789",
            }
        )
        assert user.profile.phone_number == "09123456789"
        assert user.profile.pk
        
    def test_product_factory(self):

        product = ProductFactory()

        assert product.status == ProductStatusType.PUBLISH

    def test_draft_product(self):

        product = ProductFactory(draft=True)

        assert product.status == ProductStatusType.DRAFT

    def test_coupon_expired(self):

        coupon = CouponFactory(expired=True)

        assert coupon.expiration_date < timezone.now()

    def test_order_paid(self):

        order = OrderFactory(paid=True)

        assert order.status == OrderStatusType.paid

    def test_payment_success(self):

        payment = PaymentFactory(success=True)

        assert payment.status == PaymentStatusType.SUCCESS
        