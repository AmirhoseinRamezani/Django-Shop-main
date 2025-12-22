from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from dashboard.permissions import HasAdminAccessPermission
from django.utils import timezone
from django.db.models import Sum, Count

# Import required models
from order.models import OrderModel, OrderStatusType
from shop.models import ProductModel
from accounts.models import User
from order.models import CouponModel


class AdminDashboardHomeView(LoginRequiredMixin, HasAdminAccessPermission, TemplateView):
    """
    Admin dashboard main page with statistics
    """
    template_name = "dashboard/admin/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.now().date()

        # Orders
        orders = OrderModel.objects.all()
        success_orders = orders.filter(status=OrderStatusType.success)    
        # Orders statistics
        context["total_orders"] = OrderModel.objects.count()
        context["successful_orders"] = OrderModel.objects.filter(
            status=OrderStatusType.success.value
        ).count()
        context["today_orders"] = orders.filter(created_date__date=today).count()

        # Products statistics
        context["total_products"] = ProductModel.objects.count()
        context["out_of_stock_products"] = ProductModel.objects.filter(stock=0).count()
        
        # Revenue
        context["total_revenue"] = (
            success_orders.aggregate(total=Sum("total_price"))["total"] or 0
        )

        context["today_revenue"] = (
            success_orders.filter(created_date__date=today)
            .aggregate(total=Sum("total_price"))["total"] or 0
        )

        # Users statistics (exclude superusers)
        context["total_users"] = User.objects.filter(is_superuser=False, is_active=True).count()

        # Coupons statistics (only active & not expired)
        context["active_coupons"] = CouponModel.objects.filter(
            is_active=True
        ).count()

        return context
