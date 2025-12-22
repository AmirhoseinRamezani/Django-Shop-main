from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from dashboard.permissions import HasAdminAccessPermission
from order.models import OrderModel, OrderStatusType
from payments.models import PaymentModel
from accounts.models import User


class AdminDashboardHomeView(LoginRequiredMixin, HasAdminAccessPermission, TemplateView):
    template_name = "dashboard/admin/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["orders_total"] = OrderModel.objects.count()
        context["orders_success"] = OrderModel.objects.filter(
            status=OrderStatusType.success
        ).count()
        context["orders_failed"] = OrderModel.objects.filter(
            status=OrderStatusType.failed
        ).count()

        context["payments_total"] = PaymentModel.objects.count()
        context["users_total"] = User.objects.count()

        return context
