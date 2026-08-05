# order/policies/refund.py

from order.services.coupon import CouponService
from django.utils.translation import gettext_lazy as _

class RefundPolicy:

    @staticmethod
    def rollback_coupon(order):

        if not order.coupon:
            return

        CouponService.rollback(
            order.coupon,
        )