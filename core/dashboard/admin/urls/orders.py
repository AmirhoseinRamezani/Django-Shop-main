from django.urls import path
from ..views.orders import (
    AdminOrderListView,
    AdminOrderDetailView,
    AdminOrderStatusUpdateView,
)

urlpatterns = [
    path("orders/", AdminOrderListView.as_view(), name="order-list"),
    path("orders/<int:pk>/detail/", AdminOrderDetailView.as_view(), name="order-detail"),
    path("orders/<int:pk>/status/", AdminOrderStatusUpdateView.as_view(), name="order-status"),
]
