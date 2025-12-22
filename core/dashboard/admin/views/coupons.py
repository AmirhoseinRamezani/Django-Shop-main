from django.views.generic import ListView, CreateView
from django.urls import reverse_lazy
from dashboard.permissions import HasAdminAccessPermission
from coupons.models import CouponModel


class AdminCouponListView(HasAdminAccessPermission, ListView):
    """
    Admin list of coupons
    """
    model = CouponModel
    template_name = "dashboard/admin/coupons/list.html"
    context_object_name = "coupons"


class AdminCouponCreateView(HasAdminAccessPermission, CreateView):
    """
    Admin create coupon
    """
    model = CouponModel
    fields = ["code", "discount_percent", "is_active", "is_single_use", "max_usage", "expire_date"]
    template_name = "dashboard/admin/coupons/create.html"
    success_url = reverse_lazy("admin:coupon-list")
