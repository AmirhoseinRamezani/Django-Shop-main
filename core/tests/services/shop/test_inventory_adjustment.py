import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, models, transaction
from django.db.models.deletion import ProtectedError

from shop.models import (
    InventoryAdjustment,
    InventoryAdjustmentDirection,
)
from shop.services.inventory_adjustment import InventoryAdjustmentService


pytestmark = pytest.mark.django_db


@pytest.fixture
def adjustment_actor(user):
    permission = Permission.objects.get(
        content_type__app_label="shop",
        codename="adjust_product_stock",
    )
    user.user_permissions.add(permission)
    return user


def adjust(
    *,
    product,
    actor,
    direction=InventoryAdjustmentDirection.INCREASE,
    quantity=5,
    reason="Supplier delivery",
    key="inventory-adjustment-test-key",
):
    return InventoryAdjustmentService.adjust(
        product_id=product.pk,
        actor=actor,
        direction=direction,
        quantity=quantity,
        reason=reason,
        idempotency_key=key,
    )


def test_adjustment_persists_complete_audit_record(product, adjustment_actor):
    previous_stock = product.stock

    adjustment = adjust(product=product, actor=adjustment_actor)

    product.refresh_from_db()
    adjustment.refresh_from_db()

    assert product.stock == previous_stock + 5
    assert adjustment.product_id == product.pk
    assert adjustment.actor_id == adjustment_actor.pk
    assert adjustment.direction == InventoryAdjustmentDirection.INCREASE
    assert adjustment.quantity == 5
    assert adjustment.previous_stock == previous_stock
    assert adjustment.resulting_stock == previous_stock + 5
    assert adjustment.reason == "Supplier delivery"
    assert adjustment.idempotency_key == "inventory-adjustment-test-key"
    assert len(adjustment.request_fingerprint) == 64
    assert adjustment.created_at is not None


def test_same_request_replays_original_result_without_second_mutation(
    product,
    adjustment_actor,
):
    first = adjust(product=product, actor=adjustment_actor)
    product.refresh_from_db()
    stock_after_first = product.stock

    replay = adjust(product=product, actor=adjustment_actor)
    product.refresh_from_db()

    assert replay.pk == first.pk
    assert product.stock == stock_after_first
    assert InventoryAdjustment.objects.filter(
        idempotency_key=first.idempotency_key,
    ).count() == 1


def test_same_key_with_different_payload_is_rejected_without_mutation(
    product,
    adjustment_actor,
):
    first = adjust(product=product, actor=adjustment_actor)
    product.refresh_from_db()
    stock_after_first = product.stock

    with pytest.raises(ValidationError, match="different request"):
        adjust(
            product=product,
            actor=adjustment_actor,
            quantity=6,
        )

    product.refresh_from_db()
    assert product.stock == stock_after_first
    assert InventoryAdjustment.objects.count() == 1
    assert InventoryAdjustment.objects.get(pk=first.pk).quantity == 5


def test_actor_without_explicit_permission_is_rejected(product, user):
    with pytest.raises(PermissionDenied):
        adjust(product=product, actor=user)

    product.refresh_from_db()
    assert product.stock == 10
    assert InventoryAdjustment.objects.count() == 0


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"quantity": 0}, "quantity"),
        ({"quantity": -1}, "quantity"),
        ({"reason": "   "}, "reason"),
        ({"reason": ""}, "reason"),
        ({"key": " "}, "idempotency_key"),
    ],
)
def test_invalid_adjustment_input_is_rejected(
    product,
    adjustment_actor,
    kwargs,
    field,
):
    with pytest.raises(ValidationError) as exc_info:
        adjust(product=product, actor=adjustment_actor, **kwargs)

    assert field in exc_info.value.message_dict
    product.refresh_from_db()
    assert product.stock == 10
    assert InventoryAdjustment.objects.count() == 0


def test_decrease_cannot_cross_reserved_stock(product, adjustment_actor):
    product.reserved_stock = 4
    product.save(update_fields=("reserved_stock",))

    with pytest.raises(ValidationError, match="reserved quantity"):
        adjust(
            product=product,
            actor=adjustment_actor,
            direction=InventoryAdjustmentDirection.DECREASE,
            quantity=7,
            key="reserved-stock-boundary",
        )

    product.refresh_from_db()
    assert product.stock == 10
    assert product.reserved_stock == 4
    assert InventoryAdjustment.objects.count() == 0


def test_decrease_can_reach_reserved_stock_but_not_below_it(
    product,
    adjustment_actor,
):
    product.reserved_stock = 4
    product.save(update_fields=("reserved_stock",))

    adjustment = adjust(
        product=product,
        actor=adjustment_actor,
        direction=InventoryAdjustmentDirection.DECREASE,
        quantity=6,
        key="reserved-stock-exact-boundary",
    )

    product.refresh_from_db()
    assert product.stock == 4
    assert adjustment.resulting_stock == 4


def test_stock_change_and_audit_insert_roll_back_together(
    product,
    adjustment_actor,
    mocker,
):
    original_stock = product.stock
    mocker.patch.object(
        InventoryAdjustment,
        "save",
        side_effect=RuntimeError("audit insert failed"),
    )

    with pytest.raises(RuntimeError, match="audit insert failed"):
        adjust(product=product, actor=adjustment_actor)

    product.refresh_from_db()
    assert product.stock == original_stock
    assert InventoryAdjustment.objects.count() == 0


def test_audit_record_cannot_be_created_outside_the_application_service(
    product,
    adjustment_actor,
):
    adjustment = InventoryAdjustment(
        product=product,
        actor=adjustment_actor,
        direction=InventoryAdjustmentDirection.INCREASE,
        quantity=1,
        previous_stock=10,
        resulting_stock=11,
        reason="Direct model write",
        idempotency_key="direct-model-write",
        request_fingerprint="0" * 64,
    )

    with pytest.raises(ValidationError, match="InventoryAdjustmentService"):
        adjustment.save()

    assert InventoryAdjustment.objects.count() == 0


def test_database_rejects_inconsistent_stock_math(product, adjustment_actor):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            invalid_adjustment = InventoryAdjustment(
                product=product,
                actor=adjustment_actor,
                direction=InventoryAdjustmentDirection.DECREASE,
                quantity=3,
                previous_stock=2,
                resulting_stock=0,
                reason="Invalid direct write",
                idempotency_key="invalid-math-direct-write",
                request_fingerprint="0" * 64,
            )
            # Bypass the application guard only to exercise the database CHECK.
            models.Model.save(invalid_adjustment, force_insert=True)


def test_adjustment_is_immutable_and_cannot_be_deleted(product, adjustment_actor):
    adjustment = adjust(product=product, actor=adjustment_actor)

    adjustment.reason = "Tampered"
    with pytest.raises(ValidationError, match="immutable"):
        adjustment.save()

    with pytest.raises(ValidationError, match="cannot be deleted"):
        adjustment.delete()


def test_product_and_actor_are_protected_from_deletion(product, adjustment_actor):
    adjust(product=product, actor=adjustment_actor)

    with pytest.raises(ProtectedError):
        product.delete()

    with pytest.raises(ProtectedError):
        adjustment_actor.delete()



def test_admin_cannot_edit_product_stock_or_write_adjustment_records(
    rf,
    admin_user,
):
    from django.contrib.admin.sites import AdminSite
    from shop.admin import InventoryAdjustmentAdmin, ProductAdmin
    from shop.models import ProductModel

    request = rf.get("/admin/")
    request.user = admin_user

    product_admin = ProductAdmin(ProductModel, AdminSite())
    adjustment_admin = InventoryAdjustmentAdmin(InventoryAdjustment, AdminSite())

    assert {"stock", "reserved_stock"}.issubset(
        set(product_admin.get_readonly_fields(request))
    )
    assert adjustment_admin.has_add_permission(request) is False
    assert adjustment_admin.has_change_permission(request) is False
    assert adjustment_admin.has_delete_permission(request) is False