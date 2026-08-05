# # tests/builders/payment_builder.py
# from payment.models import PaymentStatusType
# from tests.factories.payment import PaymentFactory


# class PaymentBuilder():

#     def __init__(self, order):
#         self.order = order
#         self.kwargs = {}

#     @classmethod
#     def for_order(cls, order):
#         return cls(order)

#     def pending(self):
#         self.kwargs["status"] = PaymentStatusType.pending
#         return self

#     def success(self):
#         # self.kwargs["status"] = PaymentStatusType.success
#         self.kwargs.update(
#             status=PaymentStatusType.success,
#             ref_id=999999,
#         )
#         return self

#     def failed(self):
#         self.kwargs["status"] = PaymentStatusType.failed
#         return self

#     def consumed(self):
#         self.kwargs["is_consumed"] = True
#         return self
    
#     def refunded(self):
#         self.kwargs["is_refunded"] = True
#         return self

#     def amount(self, amount):
#         self.kwargs["amount"] = amount
#         return self

#     def build(self):
#         return PaymentFactory(
#             order=self.order,
#             **self.kwargs,
#         )
from __future__ import annotations

from django.utils import timezone

from payment.models import (
    PaymentStatusType,
)

from tests.builders.base import BaseBuilder

from tests.factories.payment import (
    PaymentFactory,
)


class PaymentBuilder(BaseBuilder):
    """
    Builder for PaymentModel.

    Examples
    --------

    PaymentBuilder().build()

    PaymentBuilder().success().build()

    PaymentBuilder().failed().build()

    PaymentBuilder().pending().build()

    PaymentBuilder().success().consumed().build()

    PaymentBuilder().success().refunded().build()

    PaymentBuilder().for_order(order).build()

    """

    factory = PaymentFactory

    # --------------------------------------------------

    def for_order(self, order):

        return self.with_attrs(
            order=order,
            amount=order.final_price,
        )

    # --------------------------------------------------

    def authority(self, authority):

        return self.with_attrs(
            authority_id=authority,
        )

    # --------------------------------------------------

    def ref(self, ref_id):

        return self.with_attrs(
            ref_id=ref_id,
        )

    # --------------------------------------------------

    def amount(self, amount):

        return self.with_attrs(
            amount=amount,
        )

    # --------------------------------------------------

    def gateway(self, gateway):

        return self.with_attrs(
            gateway=gateway,
        )

    # --------------------------------------------------

    def pending(self):

        return self.with_attrs(
            status=PaymentStatusType.pending,
            paid_date=None,
        )

    # --------------------------------------------------

    def success(self):

        return self.with_attrs(

            status=PaymentStatusType.success,

            paid_date=timezone.now(),
        )

    # --------------------------------------------------

    def failed(self):

        return self.with_attrs(

            status=PaymentStatusType.failed,

            paid_date=None,
        )

    # --------------------------------------------------

    def consumed(self):

        return self.with_attrs(
            is_consumed=True,
        )

    # --------------------------------------------------

    def not_consumed(self):

        return self.with_attrs(
            is_consumed=False,
        )

    # --------------------------------------------------

    def refunded(self):

        """
        Payment remains SUCCESS.

        Refund is tracked separately.

        """

        return self.with_attrs(

            status=PaymentStatusType.success,

            is_refunded=True,

            paid_date=timezone.now(),
        )

    # --------------------------------------------------

    def response(self, data):

        return self.with_attrs(
            response_json=data,
        )

    # --------------------------------------------------

    def response_code(self, code):

        return self.with_attrs(
            response_code=code,
        )

    # --------------------------------------------------

    def build(self, **override):

        attrs = self._attrs.copy()

        attrs.setdefault(
            "authority_id",
            "AUTH-TEST",
        )

        attrs.setdefault(
            "gateway",
            "ZARINPAL",
        )

        attrs.setdefault(
            "response_json",
            {},
        )

        return super().build(**attrs, **override)