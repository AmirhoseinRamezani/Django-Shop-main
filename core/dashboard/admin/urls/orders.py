from django.urls import path
from dashboard.admin.views.order import (
    AdminOrderListView,
    AdminOrderDetailView,
    AdminOrderInvoiceView,
    AdminOrderRefundView,
)

app_name = "orders"

urlpatterns = [
    path("order/list/",AdminOrderListView.as_view(),name="order-list"),
    path("order/<int:pk>/detail/",AdminOrderDetailView.as_view(),name="order-detail"),
    path("order/<int:pk>/invoice/",AdminOrderInvoiceView.as_view(),name="order-invoice"),
    path(
        "orders/<int:pk>/refund/",
        AdminOrderRefundView.as_view(),
        name="order-refund"
    ),

]
