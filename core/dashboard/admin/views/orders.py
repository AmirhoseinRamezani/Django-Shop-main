from django.views.generic import UpdateView,DeleteView,CreateView,ListView,DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from dashboard.permissions import HasAdminAccessPermission

from dashboard.admin.forms import *
from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse_lazy
from django.shortcuts import redirect
from django.contrib import messages
from django.core.exceptions import FieldError
from order.models import OrderModel,OrderStatusType

from django.utils.timezone import now



class AdminOrderListView(LoginRequiredMixin, HasAdminAccessPermission, ListView):
    """
    Admin view to list and manage all orders.
    Supports filtering by order status.
    """

    template_name = "dashboard/admin/orders/list.html"
    model = OrderModel
    context_object_name = "orders"
    paginate_by = 20
    ordering = ["-created_at"]

    def get_queryset(self):
        queryset = super().get_queryset()

        # Optional filter by status (via query param)
        status = self.request.GET.get("status")
        if status:
            queryset = queryset.filter(status=status)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Order statistics
        context["total_orders"] = OrderModel.objects.count()
        context["successful_orders"] = OrderModel.objects.filter(
            status=OrderStatusType.success.value
        ).count()

        # Today's orders
        today = now().date()
        context["today_orders"] = OrderModel.objects.filter(
            created_at__date=today
        ).count()

        # Order status choices (for filter UI)
        context["status_choices"] = OrderStatusType.choices

        return context

class AdminOrderDetailView(LoginRequiredMixin, DetailView):
    """
    Admin view to see full order details
    """
    model = OrderModel
    template_name = "dashboard/admin/orders/order_detail.html"
    context_object_name = "order"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("user", "payment", "coupon")
        )
        
class AdminOrderInvoiceView(LoginRequiredMixin, DetailView):
    """
    Admin invoice preview for an order
    """
    model = OrderModel
    template_name = "dashboard/admin/orders/order_invoice.html"
    context_object_name = "order"
