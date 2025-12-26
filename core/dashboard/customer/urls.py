
from django.urls import path, include
from . import views
from .views.coupon import ApplyCouponView


urlpatterns = [
    
    path("apply-coupon/", ApplyCouponView.as_view(), name="apply-coupon"),
]