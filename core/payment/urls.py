from django.urls import path
from .views import PaymentVerifyView

app_name = "payment"

urlpatterns = [
    path("verify/", PaymentVerifyView.as_view(), name="verify"),
]
