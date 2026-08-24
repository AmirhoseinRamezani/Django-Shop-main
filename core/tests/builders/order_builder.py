# tests/builders/order_builder.py
"""
Order scenario builders.

Builders compose existing order/shop/account factories.
They do not implement order business logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from accounts.models import User
from order.models import OrderItemModel ,OrderModel ,CouponModel
from shop.models import ProductModel

from tests.builders.accounts_builder import AccountScenarioBuilder
from tests.builders.base import BaseBuilder
from tests.factories.order import (
    OrderFactory,
    OrderItemFactory,
)
from tests.factories.shop import (
    CouponFactory,
    ProductFactory,
)

@dataclass(frozen=True)
class OrderScenario:
    """Result of an order scenario."""

    user: User
    order: OrderModel
    items: tuple[OrderItemModel, ...] = ()
    coupon: Optional[CouponModel] = None

class OrderScenarioBuilder(BaseBuilder[OrderScenario]):
    """
    Builder for meaningful order test scenarios.

    The builder composes existing factories and does not implement
    pricing, stock, coupon, or order-state business rules.
    """

    __slots__ = (
        "_user",
        "_coupon",
        "_with_coupon",
        "_item_count",
        "_products",
        "_order_trait",
    )

    def __init__(self) -> None:
        super().__init__()

        self._user: Optional[User] = None
        self._coupon: Optional[CouponModel] = None
        self._with_coupon = False
        self._item_count = 0
        self._products: list[ProductModel] = []
        self._order_trait: Optional[str] = None

    def with_user(self, user: User) -> OrderScenarioBuilder:
        """Reuse an externally-created user."""
        self._user = user
        return self

    def with_coupon(
        self,
        coupon: Optional[CouponModel] = None,
    ) -> OrderScenarioBuilder:
        """
        Attach a coupon to the order.

        An externally supplied coupon is reused. Otherwise the existing
        CouponFactory creates the coupon during build().
        """
        self._with_coupon = True

        if coupon is not None:
            self._coupon = coupon

        return self

    def with_items(
        self,
        count: int = 1,
        products: Optional[list[ProductModel]] = None,
    ) -> OrderScenarioBuilder:
        """
        Request order items.

        Supplied products are reused. Missing products are created from
        ProductFactory during build().
        """
        if count < 0:
            raise ValueError(
                "count must be greater than or equal to zero"
            )

        if products is not None and len(products) > count:
            raise ValueError(
                "The number of supplied products cannot exceed item count."
            )

        self._item_count = count

        if products is not None:
            self._products = list(products)

        return self

    def paid(self) -> OrderScenarioBuilder:
        self._order_trait = "paid"
        return self

    def processing(self) -> OrderScenarioBuilder:
        self._order_trait = "processing"
        return self

    def shipped(self) -> OrderScenarioBuilder:
        self._order_trait = "shipped"
        return self

    def delivered(self) -> OrderScenarioBuilder:
        self._order_trait = "delivered"
        return self

    def cancelled(self) -> OrderScenarioBuilder:
        self._order_trait = "cancelled"
        return self

    def expired(self) -> OrderScenarioBuilder:
        self._order_trait = "expired"
        return self

    def build(self) -> OrderScenario:
        self._mark_built()

        user = self._resolve_user()

        coupon = self._resolve_coupon()

        order_kwargs: dict[str, object] = {
            "user": user,
        }

        if coupon is not None:
            order_kwargs["coupon"] = coupon

        if self._order_trait is not None:
            order_kwargs[self._order_trait] = True

        order = OrderFactory.create(**order_kwargs)

        items = self._build_items(order)

        return OrderScenario(
            user=user,
            order=order,
            items=tuple(items),
            coupon=coupon,
        )

    def _resolve_user(self) -> User:
        if self._user is not None:
            return self._user

        return AccountScenarioBuilder().build().user

    def _resolve_coupon(self) -> Optional[CouponModel]:
        if not self._with_coupon:
            return None

        if self._coupon is not None:
            return self._coupon

        return CouponFactory.create()

    def _build_items(
        self,
        order: OrderModel,
    ) -> list[OrderItemModel]:
        items: list[OrderItemModel] = []

        for index in range(self._item_count):
            product = self._resolve_product(index)

            item = OrderItemFactory.create(
                order=order,
                product=product,
            )

            items.append(item)

        return items

    def _resolve_product(self, index: int) -> ProductModel:
        if index < len(self._products):
            return self._products[index]

        return ProductFactory.create()