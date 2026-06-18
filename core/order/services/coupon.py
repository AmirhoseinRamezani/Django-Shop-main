# order/services/coupon.py
from django.core.exceptions import ValidationError
from order.models import CouponModel
from django.utils.translation import gettext as _

class CouponService:
    """
    Centralized coupon logic
    """

    @staticmethod
    def get_valid_coupon(code: str) -> CouponModel:
        try:
            coupon = CouponModel.objects.get(code__iexact=code.strip())
        except CouponModel.DoesNotExist:
            raise ValidationError(_("Discount code is not valid"))

        if not coupon.is_valid():
            raise ValidationError(_("The discount code is expired or inactive"))

        return coupon
