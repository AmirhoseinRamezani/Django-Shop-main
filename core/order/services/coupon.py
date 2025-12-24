
from django.core.exceptions import ValidationError
from order.models import CouponModel


class CouponService:
    """
    Centralized coupon logic
    """

    @staticmethod
    def get_valid_coupon(code: str) -> CouponModel:
        try:
            coupon = CouponModel.objects.get(code__iexact=code.strip())
        except CouponModel.DoesNotExist:
            raise ValidationError("کد تخفیف معتبر نیست")

        if not coupon.is_valid():
            raise ValidationError("کد تخفیف منقضی یا غیر فعال است")

        return coupon
