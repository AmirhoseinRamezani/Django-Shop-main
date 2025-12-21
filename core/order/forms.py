from django import forms
from django.utils import timezone
from .models import UserAddressModel, CouponModel


class CheckOutForm(forms.Form):
    address_id = forms.IntegerField()
    coupon = forms.CharField(required=False)

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request")
        super().__init__(*args, **kwargs)

    def clean_address_id(self):
        address_id = self.cleaned_data["address_id"]
        try:
            return UserAddressModel.objects.get(
                id=address_id,
                user=self.request.user
            )
        except UserAddressModel.DoesNotExist:
            raise forms.ValidationError("آدرس معتبر نیست")

    def clean_coupon(self):
        code = self.cleaned_data.get("coupon")
        if not code:
            return None

        try:
            coupon = CouponModel.objects.get(code=code)
        except CouponModel.DoesNotExist:
            raise forms.ValidationError("کد تخفیف نامعتبر است")

        if coupon.expiration_date and coupon.expiration_date < timezone.now():
            raise forms.ValidationError("کد تخفیف منقضی شده است")

        if coupon.used_by.filter(id=self.request.user.id).exists():
            raise forms.ValidationError("این کد قبلاً استفاده شده")

        if coupon.used_by.count() >= coupon.max_limit_usage:
            raise forms.ValidationError("سقف استفاده از کد پر شده")

        return coupon
