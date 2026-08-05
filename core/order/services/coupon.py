# order/services/coupon.py
from django.db import transaction
from django.db.models import F
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from order.models import CouponModel

class CouponService:
    """
    Canonical Coupon Domain Service.

    Responsible for:

    - validation
    - lookup
    - consume
    - rollback
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
    

    # @staticmethod
    # @transaction.atomic
    # def consume(coupon: CouponModel):

    #     CouponModel.objects.filter(
    #         id=coupon.id
    #     ).update(
    #         used_count=F("used_count") + 1
    #     )
    @staticmethod
    @transaction.atomic
    def consume(coupon: CouponModel):

        updated = (
            CouponModel.objects
            .filter(
                id=coupon.id,
                is_active=True,
            )
            .exclude(
                used_count=F("max_usage"),
            )
            .update(
                used_count=F("used_count") + 1
            )
        )

        if updated == 0:
            raise ValidationError(
                _("Coupon cannot be consumed")
            )

    @staticmethod
    @transaction.atomic
    def rollback(coupon: CouponModel):

        CouponModel.objects.filter(
            id=coupon.id,
            used_count__gt=0,
        ).update(
            used_count=F("used_count") - 1
        )
