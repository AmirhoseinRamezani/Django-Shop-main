from django import forms
from .models import ReviewModel
from shop.models import ProductModel, ProductStatusType


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
            raise forms.ValidationError("این محصول قابل ثبت نظر نیست")

        if ReviewModel.objects.filter(user=user, product=product).exists():
            raise forms.ValidationError("شما قبلاً برای این محصول نظر ثبت کرده‌اید")

        return cleaned_data
