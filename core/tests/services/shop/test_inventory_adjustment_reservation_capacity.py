import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from shop.constants import ProductStatusType
from shop.models import InventoryAdjustment, InventoryAdjustmentDirection, ProductModel
from shop.services.inventory_adjustment import InventoryAdjustmentService


@pytest.mark.django_db
def test_increase_preserves_capacity_for_future_reservation_release():
    user_model = get_user_model()
    actor = user_model.objects.create_user(
        email="inventory-adjuster@example.test",
        password="test-password",
        is_active=True,
    )
    content_type = ContentType.objects.get_for_model(InventoryAdjustment)
    permission = Permission.objects.get(
        content_type=content_type,
        codename="adjust_product_stock",
    )
    actor.user_permissions.add(permission)

    product = ProductModel.objects.create(
        user=actor,
        title="Capacity boundary product",
        slug="capacity-boundary-product",
        description="test",
        price=100,
        stock=2_147_483_640,
        reserved_stock=5,
        sku="CAPACITY-BOUNDARY-001",
        status=ProductStatusType.PUBLISH,
    )

    with pytest.raises(ValidationError):
        InventoryAdjustmentService.adjust(
            product_id=product.pk,
            actor=actor,
            direction=InventoryAdjustmentDirection.INCREASE,
            quantity=3,
            reason="test capacity boundary",
            idempotency_key="g3-capacity-overflow",
        )

    product.refresh_from_db()
    assert product.stock == 2_147_483_640
    assert product.reserved_stock == 5