from django.views.generic import FormView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.urls import reverse
from django.core.exceptions import ValidationError

from order.permissions import HasCustomerAccessPermission
from order.forms import CheckOutForm
from order.services import OrderService
from order.models import CouponModel
from cart.cart import CartSession
from cart.models import CartModel
from payment.services import PaymentService

class OrderCheckOutView(LoginRequiredMixin, HasCustomerAccessPermission, FormView):
    """
    Creates order draft and redirects user to payment gateway.
    NO cart or coupon consumption here.
    """
    template_name = "order/checkout.html"
    form_class = CheckOutForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs

    def form_valid(self, form):
        
        user = self.request.user
        address = form.cleaned_data["address_id"]

        cart = CartModel.objects.select_related("user").get(user=user)

        # coupon from session (single source of truth)
        coupon = None
        coupon_id = self.request.session.get("coupon_id")
        if coupon_id:
            coupon = CouponModel.objects.filter(id=coupon_id).first()

        try:
            order = OrderService.create_online_order(
                user=user,
                address=address,
                cart=cart,
                coupon=coupon,
            )
        except ValidationError as e:
            form.add_error(None, e.message)
            return self.form_invalid(form)
        
        payment_url = PaymentService.start_payment(
            order=order,
            callback_url=self.request.build_absolute_uri(
                reverse("payment:verify")
            ),
        )
        return redirect(payment_url)
