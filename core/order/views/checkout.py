from django.views.generic import FormView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.core.exceptions import ValidationError

from order.permissions import HasCustomerAccessPermission
from order.forms import CheckOutForm
from order.services import OrderService
from order.models import CouponModel
from cart.cart import CartSession
from cart.models import CartModel
from payment.zarinpal_client import ZarinPalSandbox
from payment.models import PaymentModel


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

        return redirect(self._create_payment_url(order))

    def _create_payment_url(self, order):
        """
        Create payment request and attach payment to order
        """
        zarinpal = ZarinPalSandbox()
        response = zarinpal.payment_request(order.get_price())

        payment = PaymentModel.objects.create(
            authority_id=response["Authority"],
            amount=order.get_price(),
        )

        order.payment = payment
        order.save(update_fields=["payment"])

        return zarinpal.generate_payment_url(payment.authority_id)
