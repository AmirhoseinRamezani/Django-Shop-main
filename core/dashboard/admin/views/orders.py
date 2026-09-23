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
from payment.services.refund import RefundService
from payment.enums import PaymentStatusType
from order.policies import OrderPolicy
from django.utils.timezone import now

from django.utils.translation import gettext_lazy as _


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
                status=OrderStatusType.paid
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
            status=OrderStatusType.paid
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
    def post(self, request, pk):
        order = get_object_or_404(
            OrderModel,
            pk=pk,
        )

        payment = (
            order.payments
            .filter(status=PaymentStatusType.SUCCESS)
            .order_by("-updated_date", "-id")
            .first()
        )
        if payment is None:
            messages.error(request, _("No successful payment is available for refund."))
            return redirect(
                reverse("dashboard_admin:order-detail", kwargs={"pk": pk})
            )

        RefundService.refund_order(
            order_id=order.pk,
            payment_id=payment.pk,
            actor=request.user,
            idempotency_key=f"admin-order-refund:{order.pk}:{payment.pk}",
        )

        messages.success(request, _("Order refund request processed."))
        return redirect(
            reverse("dashboard_admin:order-detail", kwargs={"pk": pk})
        )