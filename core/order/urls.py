from django.urls import path
from .views import OrderCheckoutView, OrderCompletedView, OrderFailedView

app_name = "order"

urlpatterns = [
    path("checkout/", OrderCheckoutView.as_view(), name="checkout"),
    path("completed/", OrderCompletedView.as_view(), name="completed"),
    path("failed/", OrderFailedView.as_view(), name="failed"),
]