# order/views/result.py
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView
from order.permissions import HasCustomerAccessPermission
from payment.models import PaymentResolution, PaymentResolutionStatus


class OrderCompletedView(LoginRequiredMixin, HasCustomerAccessPermission, TemplateView):
    template_name = "order/completed.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        order_id = self.request.session.get("payment_resolution_order_id")
        if order_id is None:
            context["payment_resolution_open"] = False
            return context

        try:
            order_id = int(order_id)
        except (TypeError, ValueError):
            self.request.session.pop("payment_resolution_order_id", None)
            context["payment_resolution_open"] = False
            return context
        if order_id <= 0:
            self.request.session.pop("payment_resolution_order_id", None)
            context["payment_resolution_open"] = False
            return context

        # Session data is only a presentation hint. It must never be treated
        # as authority, and stale/foreign IDs must not turn the result page into
        # a 404 or disclose whether another customer's payment has a Resolution.
        has_open_resolution = PaymentResolution.objects.filter(
            payment__order_id=order_id,
            payment__order__user_id=self.request.user.pk,
            status=PaymentResolutionStatus.OPEN,
            payment__is_consumed=False,
        ).exists()
        context["payment_resolution_open"] = has_open_resolution
        if not has_open_resolution:
            self.request.session.pop("payment_resolution_order_id", None)
        return context


class OrderFailedView(LoginRequiredMixin, HasCustomerAccessPermission, TemplateView):
    template_name = "order/failed.html"
