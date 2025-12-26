from django.views.generic import ListView, CreateView, UpdateView ,DeleteView
from django.urls import reverse_lazy
from dashboard.permissions import HasAdminAccessPermission
from order.models import CouponModel
from dashboard.admin.forms.coupons import CouponForm

class AdminCouponListView(HasAdminAccessPermission,ListView):
    """
    Admin list of coupons
    """
    model = CouponModel
    template_name = "dashboard/admin/coupons/list.html"
    context_object_name = "object_list"


class AdminCouponCreateView(HasAdminAccessPermission,CreateView):
    """
    Admin create coupon
    """
    model = CouponModel
    fields = ["code", "discount_percent", "is_active", "is_single_use", "max_usage", "expire_date"]
    template_name = "dashboard/admin/coupons/create.html"
    success_url = reverse_lazy("dashboard:admin:coupon-list")

class AdminCouponUpdateView(HasAdminAccessPermission,UpdateView):
    model = CouponModel
    form_class = CouponForm
    template_name = "dashboard/admin/coupons/coupons-edit.html"
    success_url = reverse_lazy("dashboard:admin:coupon-list")
    
class AdminCouponDeleteView(HasAdminAccessPermission, DeleteView):
    model = CouponModel
    template_name = "dashboard/admin/coupons/coupon-delete.html"
    success_url = reverse_lazy("dashboard:admin:coupon-list")