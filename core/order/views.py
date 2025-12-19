from django.views.generic import FormView, TemplateView
from django.shortcuts import redirect
from django.urls import reverse_lazy
from order.forms import OnlineCheckoutForm
from order.permissions import IsCustomer
from order.services import OrderService
from cart.models import CartModel
from payment.services import PaymentService


class OrderCheckoutView(IsCustomer, FormView):
    template_name = "order/checkout.html"
    form_class = OnlineCheckoutForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        kwargs["shop"] = self.request.shop
        return kwargs

    def form_valid(self, form):
        cart = CartModel.objects.get(user=self.request.user)
        order = OrderService.create_online_order(
            user=self.request.user,
            address=form.cleaned_data["address_id"],
            cart=cart,
            coupon=form.cleaned_data.get("coupon_code")
        )
        return redirect(PaymentService.start_payment(order))


class OrderCompletedView(TemplateView):
    template_name = "order/completed.html"


class OrderFailedView(TemplateView):
    template_name = "order/failed.html"
