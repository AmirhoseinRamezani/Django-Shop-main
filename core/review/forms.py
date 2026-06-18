from django import forms
from .models import ReviewModel
from shop.models import ProductModel, ProductStatusType
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _



class SubmitReviewForm(forms.ModelForm):
    class Meta:
        model = ReviewModel
        fields = ['product', 'rate', 'description']
        error_messages = {
            'description': {
                'required': 'فیلد توضیحات اجباری است',
            },
        }

    def clean(self):
        cleaned_data = super().clean()
        product = cleaned_data.get('product')
        user = self.initial.get("user")

        if not ProductModel.objects.filter(
            id=product.id,
            status=ProductStatusType.publish.value
        ).exists():
            raise forms.ValidationError(_("This product cannot be commented on"))

        if ReviewModel.objects.filter(user=user, product=product).exists():
            raise forms.ValidationError(_("You have already commented on this product"))

        return cleaned_data
