import pytest
from django.core.exceptions import ValidationError

from shop.models import InventoryAdjustment, InventoryAdjustmentDirection
from shop.services.inventory_adjustment import InventoryAdjustmentService
from tests.concurrency.base import ConcurrentRunner
from tests.factories.accounts import UserFactory
from tests.factories.shop import ProductFactory


pytestmark = pytest.mark.django_db(transaction=True)


def test_concurrent_same_idempotency_request_applies_stock_delta_once():
    product = ProductFactory(stock=10)
    actor = UserFactory(superuser=True)
    results = []
    key = "concurrent-identical-adjustment"

    def adjust_stock():
        result = InventoryAdjustmentService.adjust(
            product_id=product.pk,
            actor=actor,
            direction=InventoryAdjustmentDirection.INCREASE,
            quantity=3,
            reason="Concurrent supplier receipt",
            idempotency_key=key,
        )
        results.append(result.pk)

    ConcurrentRunner().run(adjust_stock, adjust_stock)

    product.refresh_from_db()
    assert product.stock == 13
    assert len(set(results)) == 1
    assert InventoryAdjustment.objects.filter(idempotency_key=key).count() == 1


def test_global_key_race_with_different_payload_rolls_back_losing_product_update():
    first_product = ProductFactory(stock=10)
    second_product = ProductFactory(stock=20)
    actor = UserFactory(superuser=True)
    key = "concurrent-global-key-conflict"
    results = []

    def adjust_product(product, quantity, reason):
        try:
            result = InventoryAdjustmentService.adjust(
                product_id=product.pk,
                actor=actor,
                direction=InventoryAdjustmentDirection.INCREASE,
                quantity=quantity,
                reason=reason,
                idempotency_key=key,
            )
        except ValidationError:
            results.append(("conflict", product.pk))
        else:
            results.append(("success", result.product_id))

    ConcurrentRunner().run(
        lambda: adjust_product(first_product, 2, "First product adjustment"),
        lambda: adjust_product(second_product, 4, "Different product adjustment"),
    )

    first_product.refresh_from_db()
    second_product.refresh_from_db()

    assert sorted(kind for kind, _ in results) == ["conflict", "success"]
    successful_product_id = next(
        product_id for kind, product_id in results if kind == "success"
    )
    assert (
        first_product.stock == 12
        if successful_product_id == first_product.pk
        else first_product.stock == 10
    )
    assert (
        second_product.stock == 24
        if successful_product_id == second_product.pk
        else second_product.stock == 20
    )
    assert InventoryAdjustment.objects.filter(idempotency_key=key).count() == 1


def test_concurrent_distinct_adjustments_on_one_product_do_not_lose_updates():
    product = ProductFactory(stock=10)
    actor = UserFactory(superuser=True)
    results = []

    def adjust_stock(key):
        result = InventoryAdjustmentService.adjust(
            product_id=product.pk,
            actor=actor,
            direction=InventoryAdjustmentDirection.INCREASE,
            quantity=2,
            reason="Concurrent independent receipt",
            idempotency_key=key,
        )
        results.append(result.pk)

    ConcurrentRunner().run(
        lambda: adjust_stock("independent-adjustment-a"),
        lambda: adjust_stock("independent-adjustment-b"),
    )

    product.refresh_from_db()
    assert product.stock == 14
    assert len(set(results)) == 2
    assert InventoryAdjustment.objects.filter(
        pk__in=results,
    ).count() == 2

def test_concurrent_stock_adjustment_and_reservation_restore_preserve_capacity():
    from order.models import InventoryReservationStatus
    from order.services.inventory import InventoryService
    from tests.factories.order import OrderFactory, OrderItemFactory

    max_stock = 2_147_483_647
    product = ProductFactory(stock=max_stock - 6)
    order = OrderFactory()
    item = OrderItemFactory(order=order, product=product, quantity=2)
    InventoryService.reserve(order)

    actor = UserFactory(superuser=True)

    def increase_stock():
        return InventoryAdjustmentService.adjust(
            product_id=product.pk,
            actor=actor,
            direction=InventoryAdjustmentDirection.INCREASE,
            quantity=4,
            reason="Concurrent reservation restore capacity regression",
            idempotency_key="concurrent-adjustment-reservation-restore",
        )

    ConcurrentRunner().run(
        increase_stock,
        lambda: InventoryService.restore(order),
    )

    product.refresh_from_db()
    reservation = item.inventory_reservation
    reservation.refresh_from_db()

    assert product.stock == max_stock - 2
    assert reservation.status == InventoryReservationStatus.RELEASED
    assert product.stock <= max_stock