from django.views.generic import UpdateView,DeleteView,CreateView,ListView,DetailView,View
from django.contrib.auth.mixins import LoginRequiredMixin
from dashboard.permissions import HasAdminAccessPermission
from django.shortcuts import render,get_object_or_404
from dashboard.admin.forms import *
from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse ,reverse_lazy
from django.shortcuts import redirect
from django.contrib import messages
from django.core.exceptions import FieldError
from order.models import OrderModel,OrderStatusType
from django.db import transaction
from order.services.refund import RefundService
from order.policies import OrderPolicy
from django.utils.timezone import now



class AdminOrderListView(HasAdminAccessPermission, LoginRequiredMixin, ListView):
    """
    Admin view to list and manage all orders.
    Supports filtering by order status.
    """

    template_name = "dashboard/admin/orders/order-list.html"
    model = OrderModel
    context_object_name = "orders"
    paginate_by = 20
    ordering = ["-created_date"]

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .select_related("user", "coupon")
            .prefetch_related("payments")
        )

        # Optional filter by status (via query param)
        status = self.request.GET.get("status")
        if status:
            queryset = queryset.filter(status=status)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Today's orders
        today = now().date()
        
        context.update({
            # Order statistics
            "total_orders": OrderModel.objects.count(),
            "successful_orders": OrderModel.objects.filter(
                status=OrderStatusType.success
            ).count(),
            "today_orders": OrderModel.objects.filter(
                created_date__date=today
            ).count(),
            # Order status choices (for filter UI)
            "status_choices": OrderStatusType.choices,
        })


        return context

class AdminOrderDetailView(HasAdminAccessPermission, DetailView):
    """
    Admin view to see full order details
    """
    model = OrderModel
    template_name = "dashboard/admin/orders/order-detail.html"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("user", "coupon")
            .prefetch_related("payments","order_items__product")
        )
    def get_object(self):
        order = super().get_object()
        OrderPolicy.can_view(self.request.user, order)
        return order
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["timeline"] = self.object.events.select_related("actor")
        return context
        
class AdminOrderInvoiceView(HasAdminAccessPermission, View):
    """
    Admin invoice preview for an order
    """
    model = OrderModel
    template_name = "dashboard/admin/orders/order_invoice.html"

    def get(self, request, pk):
        order = get_object_or_404(
            OrderModel,
            pk=pk,
            status=OrderStatusType.success
        )

        return render(
            request,
            "dashboard/admin/orders/invoice.html",
            {"object": order}
        )
        
class AdminOrderRefundView(
    HasAdminAccessPermission,
    LoginRequiredMixin,
    View
):
    @transaction.atomic
    def post(self, request, pk):
        order = get_object_or_404(
            OrderModel.objects.select_for_update(),
            pk=pk,
        )

        RefundService.refund_order(order=order, admin_user=request.user)

        messages.success(request, "سفارش با موفقیت مرجوع شد")
        return redirect(
            reverse("dashboard_admin:order-detail", kwargs={"pk": pk})
        )