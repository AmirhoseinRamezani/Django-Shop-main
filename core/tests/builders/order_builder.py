# tests/builders/order_builder.py
    
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