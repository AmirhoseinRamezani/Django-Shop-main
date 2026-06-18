from django import forms
from django.utils import timezone
from .models import UserAddressModel, CouponModel
from django.core.exceptions import ValidationError

from django.utils.translation import gettext_lazy as _

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
            raise forms.ValidationError(_("Invalid address"))

    def clean_coupon(self):
        code = self.cleaned_data.get("coupon")
        if not code:
            return None

        try:
            coupon = CouponModel.objects.get(code=code)
        except CouponModel.DoesNotExist:
            raise forms.ValidationError(_("Invalid discount code"))

        if coupon.expiration_date and coupon.expiration_date < timezone.now():
            raise forms.ValidationError(_("Discount code expired"))

        if coupon.used_by.filter(id=self.request.user.id).exists():
            raise forms.ValidationError(_("This code has already been used"))

        if coupon.used_by.count() >= coupon.max_limit_usage:
            raise forms.ValidationError(_("Code usage limit reached"))

        return coupon
