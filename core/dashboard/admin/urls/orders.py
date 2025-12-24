from django.urls import path
from .. import views

app_name = "orders"

urlpatterns = [
    path("order/list/",views.AdminOrderListView.as_view(),name="order-list"),
    path("order/<int:pk>/detail/",views.AdminOrderDetailView.as_view(),name="order-detail"),
    path("order/<int:pk>/invoice/",views.AdminOrderInvoiceView.as_view(),name="order-invoice"),
]
