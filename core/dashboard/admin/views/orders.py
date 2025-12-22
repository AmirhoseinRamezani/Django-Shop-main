from django.views.generic import ListView, DetailView, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin
from dashboard.permissions import HasAdminAccessPermission
from django.urls import reverse_lazy
from django.core.exceptions import FieldError
from order.models import OrderModel, OrderStatusType


class AdminOrderListView(LoginRequiredMixin, HasAdminAccessPermission, ListView):
    """
    نمایش لیست تمام سفارش‌ها برای ادمین
    """
    template_name = "dashboard/admin/orders/order-list.html"
    paginate_by = 10

    def get_paginate_by(self, queryset):
        return self.request.GET.get("page_size", self.paginate_by)

    def get_queryset(self):
        queryset = OrderModel.objects.all().select_related("user")

        if search_q := self.request.GET.get("q"):
            queryset = queryset.filter(id__icontains=search_q)

        if status := self.request.GET.get("status"):
            queryset = queryset.filter(status=status)

        if order_by := self.request.GET.get("order_by"):
            try:
                queryset = queryset.order_by(order_by)
            except FieldError:
                pass

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_types"] = OrderStatusType.choices
        context["total_items"] = self.get_queryset().count()
        return context


class AdminOrderDetailView(LoginRequiredMixin, HasAdminAccessPermission, DetailView):
    """
    مشاهده جزئیات یک سفارش
    """
    template_name = "dashboard/admin/orders/order-detail.html"
    model = OrderModel


class AdminOrderStatusUpdateView(LoginRequiredMixin, HasAdminAccessPermission, UpdateView):
    """
    تغییر وضعیت سفارش (pending / success / failed)
    """
    template_name = "dashboard/admin/orders/order-status-update.html"
    model = OrderModel
    fields = ["status"]
    success_url = reverse_lazy("dashboard:admin:order-list")
