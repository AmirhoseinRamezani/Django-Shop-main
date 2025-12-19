from django import forms
from django.utils import timezone
from order.models import CouponModel, SaleType


class OnlineCheckoutForm(forms.Form):
    address_id = forms.IntegerField()
    coupon_code = forms.CharField(required=False)

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request")
        self.shop = kwargs.pop("shop")
        super().__init__(*args, **kwargs)

    def clean_coupon_code(self):
        code = self.cleaned_data.get("coupon_code")
        if not code:
            return None

        if self.shop.sale_type != SaleType.online:
            raise forms.ValidationError("کوپن فقط برای خرید آنلاین مجاز است")

        try:
            coupon = CouponModel.objects.get(code=code)
        except CouponModel.DoesNotExist:
            raise forms.ValidationError("کد تخفیف نامعتبر است")

        if coupon.expiration_date and coupon.expiration_date < timezone.now():
            raise forms.ValidationError("کد تخفیف منقضی شده است")

        if coupon.used_by.filter(id=self.request.user.id).exists():
            raise forms.ValidationError("این کد قبلاً استفاده شده است")

        return coupon
