from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from dashboard.permissions import HasCustomerAccessPermission
from order.models import OrderModel, OrderStatusType
from shop.models import WishlistProductModel
from order.models import UserAddressModel


class CustomerDashboardHomeView( HasCustomerAccessPermission , LoginRequiredMixin, TemplateView):
    template_name = "dashboard/customer/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        # orders
        orders = OrderModel.objects.filter(user=user)
        context["orders_count"] = orders.count()
        context["last_order"] = orders.order_by("-created_date").first()
        context["successful_orders"] = orders.filter(
            status=OrderStatusType.success
        ).count()

        # addresses & wishlist
        context["addresses_count"] = UserAddressModel.objects.filter(user=user).count()
        context["wishlist_count"] = WishlistProductModel.objects.filter(user=user).count()

        return context

# Result: The dashboard goes "live", without putting pressure on the database.