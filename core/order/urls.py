from django.urls import path
from order.views.result import OrderCompletedView ,OrderFailedView  
from order.views.coupon import ApplyCouponView, ValidateCouponView
from order.views.checkout import OrderCheckOutView

app_name = "order"

urlpatterns = [
    path("checkout/", OrderCheckOutView.as_view(), name="checkout"),
    path("validate-coupon/", ValidateCouponView.as_view(), name="validate-coupon"),
    path("apply-coupon/", ApplyCouponView.as_view(), name="apply-coupon"),
    path("completed/", OrderCompletedView.as_view(), name="completed"),
    path("failed/", OrderFailedView.as_view(), name="failed"),
]
