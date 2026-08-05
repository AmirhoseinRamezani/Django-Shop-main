# tests/services/order/test_inventory.py
import pytest

from order.services.inventory import InventoryService

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

        InventoryService.decrease(
            product,
            item.quantity,
        )

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

        InventoryService.decrease(
            product,
            item1.quantity,
        )

        InventoryService.decrease(
            second_product,
            item2.quantity,
        )

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
    ):

        old_stock = product.stock

        InventoryService.increase(
            product,
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
        qty,
    ):

        old_stock = product.stock

        InventoryService.increase(
            product,
            qty,
        )

        product.refresh_from_db()

        assert product.stock == old_stock + qty


# ==========================================================
# Decrease
# ==========================================================

class TestDecrease:

    def test_decrease(
        self,
        product,
    ):

        old_stock = product.stock

        InventoryService.decrease(
            product,
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
        qty,
    ):

        old_stock = product.stock

        InventoryService.decrease(
            product,
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

        InventoryService.decrease(
            product,
            item.quantity,
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

    def test_restore_twice(
        self,
        paid_order,
        product,
    ):

        item = paid_order.order_items.first()

        InventoryService.decrease(
            product,
            item.quantity,
        )

        InventoryService.restore(
            paid_order,
        )

        stock = product.stock

        InventoryService.restore(
            paid_order,
        )

        product.refresh_from_db()

        assert product.stock == stock + item.quantity

    def test_increase_then_decrease(
        self,
        product,
    ):

        original = product.stock

        InventoryService.increase(
            product,
            10,
        )

        InventoryService.decrease(
            product,
            10,
        )

        product.refresh_from_db()

        assert product.stock == original

    def test_decrease_then_increase(
        self,
        product,
    ):

        original = product.stock

        InventoryService.decrease(
            product,
            8,
        )

        InventoryService.increase(
            product,
            8,
        )

        product.refresh_from_db()

        assert product.stock == original
        
