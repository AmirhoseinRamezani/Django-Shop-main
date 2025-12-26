from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin

from order.permissions import HasCustomerAccessPermission


class OrderCompletedView(LoginRequiredMixin, HasCustomerAccessPermission, TemplateView):
    template_name = "order/completed.html"


class OrderFailedView(LoginRequiredMixin, HasCustomerAccessPermission, TemplateView):
    template_name = "order/failed.html"
