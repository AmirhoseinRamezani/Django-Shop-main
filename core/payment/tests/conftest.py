import pytest
from decimal import Decimal
from django.utils import timezone

from order.models import OrderModel, OrderStatusType, SaleType
from payment.models import PaymentModel, PaymentStatusType
from django.contrib.auth import get_user_model
from payment.models import PaymentModel, PaymentStatusType


User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        email="test@gmail.com",
        password="123456"
    )


@pytest.fixture
def pending_order(db, user):
    return OrderModel.objects.create(
        user=user,
        sale_type=SaleType.ONLINE,
        status=OrderStatusType.pending,
        total_price=Decimal("100000"),
        expire_at=timezone.now() + timezone.timedelta(hours=1),
        full_name="Test User",
        phone="09120000000",
        email="test@test.com",
        address="addr",
        city="city",
        state="state",
        zip_code="0000",
    )


@pytest.fixture
def successful_payment(db, pending_order):
    return PaymentModel.objects.create(
        order=pending_order,
        authority_id="AUTH123",
        amount=pending_order.get_price(),
        status=PaymentStatusType.success,
        ref_id=999,
    )

@pytest.fixture
def payment(pending_order):
    return PaymentModel.objects.create(
        order=pending_order,
        authority_id="TEST_AUTH_123",
        amount=pending_order.get_price(),
        status=PaymentStatusType.pending
    )