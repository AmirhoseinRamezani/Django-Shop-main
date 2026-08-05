# tests/builders/order_builder.py
# from tests.builders.base import BaseBuilder

# from tests.factories.order import (
#     OrderFactory,
#     OrderItemFactory,
# )

# from tests.factories.shop import (
#     ProductFactory,
#     CouponFactory,
# )


# class OrderBuilder(BaseBuilder):
#     """
#     Builder for creating OrderModel instances.

#     Example:

#         order = (
#             OrderBuilder()
#             .for_user(user)
#             .paid()
#             .with_coupon()
#             .with_item()
#             .build()
#         )
#     """

#     def __init__(self):
#         super().__init__()
#         self.order_kwargs = {}
#         self.items = []

#     # -----------------------------
#     # Status
#     # -----------------------------

#     # def pending(self):
#     #     return self._trait("status", "pending")

#     # def paid(self):
#     #     return self._trait("paid")

#     # def processing(self):
#     #     return self._trait("processing")

#     # def shipped(self):
#     #     return self._trait("shipped")

#     # def delivered(self):
#     #     return self._trait("delivered")

#     # def failed(self):
#     #     return self._trait("failed")

#     # def cancelled(self):
#     #     return self._trait("cancelled")

#     # def refunded(self):
#     #     return self._trait("refunded")

#     # def expired(self):
#     #     return self._trait("expired")

#     # def payable(self):
#     #     return self._trait("payable")

#     # -------------------------
#     # traits
#     # -------------------------

#     def paid(self):
#         self.order_kwargs["paid"] = True
#         return self

#     def pending(self):
#         self.order_kwargs["status"] = "pending"
#         return self

#     def cancelled(self):
#         self.order_kwargs["cancelled"] = True
#         return self

#     def refunded(self):
#         self.order_kwargs["refunded"] = True
#         return self

#     def expired(self):
#         self.order_kwargs["expired"] = True
#         return self
    
#     # -----------------------------
#     # Items
#     # -----------------------------

#     def with_item(
#         self,
#         product=None,
#         quantity=1,
#         price=None,
#         **traits,
#     ):
#         """
#         Add order item.

#         If product is None a ProductFactory is created.
#         """

#         if product is None:
#             product = ProductFactory(**traits)

#         self.items.append(
#             dict(
#                 product=product,
#                 quantity=quantity,
#                 price=price,
#             )
#         )
#         # self._items.append(
#         #     {
#         #         "product": product,
#         #         "quantity": quantity,
#         #         "price": price,
#         #     }
#         # )

#         return self

#     def with_items(self, count):
#         for _ in range(count):
#             self.with_item()
#         return self

    
#     # -----------------------------
#     # coupen
#     # -----------------------------

#     def with_coupon(
#         self,
#         coupon=None,
#         **traits
#     ):

#         if coupon is None:
#             coupon = CouponFactory(**traits)

#         # self.order_kwargs["coupon"] = coupon
#         self.coupon = coupon
#         return self

#     # -----------------------------
#     # Build
#     # -----------------------------

#     def build(self):

#         order = OrderFactory(
#             user=self.user,
#             address=self.address, #  <=
#             **self.order_kwargs,
#         )

#         if not self.items:

#             self.with_item(
#                 product=self.product,
#                 quantity=self.quantity,
#             )
            
#         for item in self.items:

#             OrderItemFactory(
#                 order=order,
#                 product=item["product"],
#                 quantity=item["quantity"],
#                 price=item["price"] or item["product"].final_price,
#             )

#         return order
#     # -------------------------
#     # build service payload
#     # -------------------------

#     # def scenario(self):

#     #     return super().build()
    
from datetime import timedelta

from django.utils import timezone

from order.models import (
    OrderStatusType,
)

from tests.builders.base import BaseBuilder

from tests.factories.order import (
    OrderFactory,
    OrderItemFactory,
)


class OrderBuilder(BaseBuilder):

    factory = OrderFactory

    # --------------------------------------------------

    def pending(self):

        return self.with_attrs(
            status=OrderStatusType.pending
        )

    def paid(self):

        return self.with_attrs(
            status=OrderStatusType.paid
        )

    def failed(self):

        return self.with_attrs(
            status=OrderStatusType.failed
        )

    def cancelled(self):

        return self.with_attrs(
            status=OrderStatusType.cancelled
        )

    def processing(self):

        return self.with_attrs(
            status=OrderStatusType.processing
        )

    def shipped(self):

        return self.with_attrs(
            status=OrderStatusType.shipped
        )

    def delivered(self):

        return self.with_attrs(
            status=OrderStatusType.delivered
        )

    def refunded(self):

        return self.with_attrs(
            status=OrderStatusType.refunded
        )

    def returned(self):

        return self.with_attrs(
            status=OrderStatusType.returned
        )

    def return_requested(self):

        return self.with_attrs(
            status=OrderStatusType.return_requested
        )

    # --------------------------------------------------

    def with_coupon(self, coupon):

        return self.with_attrs(
            coupon=coupon,
            coupon_code=coupon.code,
            coupon_discount_percent=coupon.discount_percent,
        )

    # --------------------------------------------------

    def with_user(self, user):

        return self.with_attrs(
            user=user,
        )

    # --------------------------------------------------

    def with_address(self, address):

        return self.with_attrs(

            address=address.address,

            city=address.city,

            state=address.state,

            zip_code=address.zip_code,
        )

    # --------------------------------------------------

    def with_total(self, amount):

        return self.with_attrs(
            total_price=amount
        )

    # --------------------------------------------------

    def expired(self):

        return self.with_attrs(
            expire_at=timezone.now() - timedelta(minutes=5)
        )

    # --------------------------------------------------

    def with_expire(self, minutes):

        return self.with_attrs(
            expire_at=timezone.now()
            + timedelta(minutes=minutes)
        )

    # --------------------------------------------------

    def with_item(

        self,

        product,

        quantity=1,

        price=None,

    ):

        items = self._attrs.setdefault(
            "_items",
            [],
        )

        items.append(

            dict(

                product=product,

                quantity=quantity,

                price=price or product.final_price,
            )

        )

        return self

    # --------------------------------------------------

    def with_items(self, *items):

        self._attrs.setdefault(
            "_items",
            [],
        ).extend(items)

        return self

    # --------------------------------------------------

    def build(self, **override):

        items = self._attrs.pop(
            "_items",
            [],
        )

        order = super().build(**override)

        for item in items:

            OrderItemFactory(

                order=order,

                product=item["product"],

                quantity=item["quantity"],

                price=item["price"],
            )

        return order