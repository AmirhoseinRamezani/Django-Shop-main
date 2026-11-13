# tests/services/order/test_inventory.py
import pytest
from uuid import uuid4
from django.core.exceptions import ValidationError

from order.services.inventory import InventoryService
from shop.models import InventoryAdjustmentDirection
from shop.services.inventory_adjustment import InventoryAdjustmentService


def _manual_adjust(product, actor, direction, quantity):
    return InventoryAdjustmentService.adjust(
        product_id=product.pk,
        actor=actor,
        direction=direction,
        quantity=quantity,
        reason="Inventory service regression test",
        idempotency_key=f"inventory-test-{uuid4()}",
    )


@pytest.fixture
def inventory_adjustment_actor(db, user):
    from django.contrib.auth.models import Permission

    permission = Permission.objects.get(
        content_type__app_label="shop",
        codename="adjust_product_stock",
    )
    user.user_permissions.add(permission)
    return user


pytestmark = pytest.mark.django_db


# ==========================================================
# Reserve
# ==========================================================

class TestReserve:

    def test_reserve_stock(
        self,
        paid_order,
        product,
    ):
        old_stock = product.stock

        InventoryService.reserve(paid_order)

        product.refresh_from_db()

        item = paid_order.order_items.get(product=product)

        assert product.stock == old_stock - item.quantity

    def test_multiple_products(
        self,
        paid_order_with_two_products,
        product,
        second_product,
    ):

        old_stock_1 = product.stock
        old_stock_2 = second_product.stock

        InventoryService.reserve(
            paid_order_with_two_products,
        )

        product.refresh_from_db()
        second_product.refresh_from_db()

        item1 = (
            paid_order_with_two_products
            .order_items
            .get(product=product)
        )

        item2 = (
            paid_order_with_two_products
            .order_items
            .get(product=second_product)
        )

        assert product.stock == old_stock_1 - item1.quantity
        assert second_product.stock == old_stock_2 - item2.quantity

    def test_no_items(
        self,
        empty_order,
    ):

        InventoryService.reserve(
            empty_order,
        )

        assert empty_order.order_items.count() == 0

    def test_reserve_rejects_insufficient_stock_without_partial_decrement(
        self,
        paid_order,
        product,
    ):
        item = paid_order.order_items.get(product=product)
        product.stock = item.quantity - 1
        product.save(update_fields=["stock"])
        stock_before = product.stock

        with pytest.raises(ValidationError):
            InventoryService.reserve(paid_order)

        product.refresh_from_db()
        assert product.stock == stock_before


# ==========================================================
# Restore
# ==========================================================

class TestRestore:

    def test_restore_stock(
        self,
        paid_order,
        product,
    ):

        item = paid_order.order_items.get(
            product=product,
        )

        InventoryService.reserve(paid_order)

        product.refresh_from_db()

        reduced_stock = product.stock

        InventoryService.restore(
            paid_order,
        )

        product.refresh_from_db()

        assert product.stock == reduced_stock + item.quantity

    def test_restore_multiple_products(
        self,
        paid_order_with_two_products,
        product,
        second_product,
    ):

        item1 = paid_order_with_two_products.order_items.get(
            product=product,
        )

        item2 = paid_order_with_two_products.order_items.get(
            product=second_product,
        )

        InventoryService.reserve(paid_order_with_two_products)

        product.refresh_from_db()
        second_product.refresh_from_db()

        old1 = product.stock
        old2 = second_product.stock

        InventoryService.restore(
            paid_order_with_two_products,
        )

        product.refresh_from_db()
        second_product.refresh_from_db()

        assert product.stock == old1 + item1.quantity
        assert second_product.stock == old2 + item2.quantity

    def test_restore_empty_order(
        self,
        empty_order,
    ):

        InventoryService.restore(
            empty_order,
        )

        assert empty_order.order_items.count() == 0


# ==========================================================
# Increase
# ==========================================================

class TestIncrease:

    def test_increase(
        self,
        product,
        inventory_adjustment_actor,
    ):

        old_stock = product.stock

        _manual_adjust(
            product,
            inventory_adjustment_actor,
            InventoryAdjustmentDirection.INCREASE,
            5,
        )

        product.refresh_from_db()

        assert product.stock == old_stock + 5

    @pytest.mark.parametrize(
        "qty",
        [1, 2, 5, 20],
    )
    def test_parametrized(
        self,
        product,
        inventory_adjustment_actor,
        qty,
    ):

        old_stock = product.stock

        _manual_adjust(
            product,
            inventory_adjustment_actor,
            InventoryAdjustmentDirection.INCREASE,
            qty,
        )

        product.refresh_from_db()

        assert product.stock == old_stock + qty

    
    def test_rejects_non_positive_quantity(
        self,
        product,
        inventory_adjustment_actor,
    ):
        old_stock = product.stock

        with pytest.raises(ValidationError):
            _manual_adjust(
                product,
                inventory_adjustment_actor,
                InventoryAdjustmentDirection.INCREASE,
                0,
            )

        product.refresh_from_db()
        assert product.stock == old_stock


# ==========================================================
# Decrease
# ==========================================================

class TestDecrease:

    def test_decrease(
        self,
        product,
        inventory_adjustment_actor,
    ):

        old_stock = product.stock

        _manual_adjust(
            product,
            inventory_adjustment_actor,
            InventoryAdjustmentDirection.DECREASE,
            4,
        )

        product.refresh_from_db()

        assert product.stock == old_stock - 4

    @pytest.mark.parametrize(
        "qty",
        [1, 3, 7],
    )
    def test_parametrized(
        self,
        product,
        inventory_adjustment_actor,
        qty,
    ):

        old_stock = product.stock

        _manual_adjust(
            product,
            inventory_adjustment_actor,
            InventoryAdjustmentDirection.DECREASE,
            qty,
        )

        product.refresh_from_db()

        assert product.stock == old_stock - qty


# ==========================================================
# Atomicity
# ==========================================================

class TestAtomicity:

    def test_restore_atomic(
        self,
        paid_order,
        product,
        mocker,
    ):

        item = paid_order.order_items.first()

        InventoryService.reserve(
            paid_order,
        )

        product.refresh_from_db()

        stock_before = product.stock

        original_update = product.__class__.objects.filter

        counter = {"value": 0}

        def broken_filter(*args, **kwargs):

            qs = original_update(*args, **kwargs)

            original = qs.update

            def wrapped(**values):

                counter["value"] += 1

                if counter["value"] == 1:
                    raise RuntimeError()

                return original(**values)

            qs.update = wrapped

            return qs

        mocker.patch.object(
            product.__class__.objects,
            "filter",
            side_effect=broken_filter,
        )

        with pytest.raises(RuntimeError):

            InventoryService.restore(
                paid_order,
            )

        product.refresh_from_db()

        assert product.stock == stock_before


# ==========================================================
# Idempotency
# ==========================================================

class TestConsistency:

    def test_restore_twice_is_idempotent(
        self,
        paid_order,
        product,
    ):
        item = paid_order.order_items.first()

        InventoryService.reserve(paid_order)
        product.refresh_from_db()
        reserved_stock = product.stock

        InventoryService.restore(paid_order)
        product.refresh_from_db()
        restored_stock = product.stock

        InventoryService.restore(paid_order)
        product.refresh_from_db()

        reservation = item.inventory_reservation

        assert reserved_stock == product.stock - item.quantity
        assert restored_stock == product.stock
        assert reservation.status == "RELEASED"

    def test_increase_then_decrease(
        self,
        product,
        inventory_adjustment_actor,
    ):

        original = product.stock

        _manual_adjust(
            product,
            inventory_adjustment_actor,
            InventoryAdjustmentDirection.INCREASE,
            10,
        )

        _manual_adjust(
            product,
            inventory_adjustment_actor,
            InventoryAdjustmentDirection.DECREASE,
            10,
        )

        product.refresh_from_db()

        assert product.stock == original

    def test_decrease_then_increase(
        self,
        product,
        inventory_adjustment_actor,
    ):

        original = product.stock

        _manual_adjust(
            product,
            inventory_adjustment_actor,
            InventoryAdjustmentDirection.DECREASE,
            8,
        )

        _manual_adjust(
            product,
            inventory_adjustment_actor,
            InventoryAdjustmentDirection.INCREASE,
            8,
        )

        product.refresh_from_db()

        assert product.stock == original
        

def test_decrease_rejects_insufficient_stock(product, inventory_adjustment_actor):
    product.stock = 2
    product.save(update_fields=["stock"])

    with pytest.raises(ValidationError):
        _manual_adjust(
            product,
            inventory_adjustment_actor,
            InventoryAdjustmentDirection.DECREASE,
            3,
        )

    product.refresh_from_db()
    assert product.stock == 2


# ==========================================================
# Consumption lifecycle
# ==========================================================
class TestConsume:

    def test_consume_is_idempotent_and_does_not_decrement_stock_again(
        self,
        paid_order,
        product,
    ):
        from order.models import InventoryReservation, InventoryReservationStatus

        InventoryService.reserve(paid_order)
        product.refresh_from_db()
        reserved_stock = product.stock
        item = paid_order.order_items.get(product=product)

        assert InventoryService.consume(paid_order) == 1
        assert InventoryService.consume(paid_order) == 0

        product.refresh_from_db()
        reservation = InventoryReservation.objects.get(order_item=item)

        assert product.stock == reserved_stock
        assert reservation.status == InventoryReservationStatus.CONSUMED
        assert reservation.consumed_at is not None
        assert reservation.released_at is None

    def test_consumed_reservation_cannot_be_released(
        self,
        paid_order,
        product,
    ):
        from order.models import InventoryReservation, InventoryReservationStatus

        InventoryService.reserve(paid_order)
        InventoryService.consume(paid_order)
        product.refresh_from_db()
        reserved_stock = product.stock

        assert InventoryService.restore(paid_order) == 0

        product.refresh_from_db()
        reservation = InventoryReservation.objects.get(
            order_item=paid_order.order_items.get(product=product),
        )

        assert product.stock == reserved_stock
        assert reservation.status == InventoryReservationStatus.CONSUMED
        assert reservation.consumed_at is not None

    def test_released_reservation_cannot_be_consumed(
        self,
        paid_order,
        product,
    ):
        from order.models import InventoryReservation, InventoryReservationStatus

        InventoryService.reserve(paid_order)
        InventoryService.restore(paid_order)
        product.refresh_from_db()
        restored_stock = product.stock

        with pytest.raises(ValidationError):
            InventoryService.consume(paid_order)

        product.refresh_from_db()
        reservation = InventoryReservation.objects.get(
            order_item=paid_order.order_items.get(product=product),
        )

        assert product.stock == restored_stock
        assert reservation.status == InventoryReservationStatus.RELEASED
        assert reservation.released_at is not None
        assert reservation.consumed_at is None

    def test_consume_rejects_reservation_quantity_mismatch(
        self,
        paid_order,
        product,
    ):
        from order.models import InventoryReservation

        InventoryService.reserve(paid_order)
        item = paid_order.order_items.get(product=product)
        reservation = InventoryReservation.objects.get(order_item=item)
        reservation.quantity += 1
        reservation.save(update_fields=("quantity",))

        with pytest.raises(ValidationError, match="quantity mismatch"):
            InventoryService.consume(paid_order)

        reservation.refresh_from_db()
        assert reservation.status == "RESERVED"
        assert reservation.consumed_at is None


    def test_consume_only_mutates_reservations_owned_by_order(
        self,
        product_factory,
        order_factory,
        order_item_factory,
    ):
        from order.models import InventoryReservation, InventoryReservationStatus

        product = product_factory(stock=10)
        first_order = order_factory()
        second_order = order_factory()
        first_item = order_item_factory(
            order=first_order,
            product=product,
            quantity=2,
        )
        second_item = order_item_factory(
            order=second_order,
            product=product,
            quantity=2,
        )

        InventoryService.reserve(first_order)
        InventoryService.reserve(second_order)
        InventoryService.consume(first_order)

        first_reservation = InventoryReservation.objects.get(order_item=first_item)
        second_reservation = InventoryReservation.objects.get(order_item=second_item)

        assert first_reservation.status == InventoryReservationStatus.CONSUMED
        assert second_reservation.status == InventoryReservationStatus.RESERVED
