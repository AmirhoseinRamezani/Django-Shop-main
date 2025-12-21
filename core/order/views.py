from django.views.generic import TemplateView, FormView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from decimal import Decimal

from order.permissions import HasCustomerAccessPermission
from order.forms import CheckOutForm
from order.models import (
    OrderModel,
    OrderItemModel,
    UserAddressModel,
    CouponModel,
)
from cart.models import CartModel
from cart.cart import CartSession
from payment.zarinpal_client import ZarinPalSandbox
from payment.models import PaymentModel


class OrderCheckOutView(LoginRequiredMixin, HasCustomerAccessPermission, FormView):
    template_name = "order/checkout.html"
    form_class = CheckOutForm
    success_url = reverse_lazy("order:completed")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs

    def form_valid(self, form):
        user = self.request.user
        address = form.cleaned_data["address_id"]
        coupon = form.cleaned_data["coupon"]

        cart = CartModel.objects.get(user=user)

        order = self.create_order(address)
        self.create_order_items(order, cart)

        order.total_price = order.calculate_total_price()

        # فقط اتصال کوپن – مصرف نمی‌شود
        if coupon:
            order.coupon = coupon

        order.save()

        self.clear_cart(cart)

        return redirect(self.create_payment_url(order))

    def create_payment_url(self, order):
        zarinpal = ZarinPalSandbox()
        response = zarinpal.payment_request(order.get_price())

        payment = PaymentModel.objects.create(
            authority_id=response["Authority"],
            amount=order.get_price(),
        )

        order.payment = payment
        order.save(update_fields=["payment"])

        return zarinpal.generate_payment_url(payment.authority_id)

    def create_order(self, address):
        return OrderModel.objects.create(
            user=self.request.user,
            address=address.address,
            state=address.state,
            city=address.city,
            zip_code=address.zip_code,
        )

    def create_order_items(self, order, cart):
        for item in cart.cart_items.all():
            OrderItemModel.objects.create(
                order=order,
                product=item.product,
                quantity=item.quantity,
                price=item.product.final_price,
            )

    def clear_cart(self, cart):
        cart.cart_items.all().delete()
        CartSession(self.request.session).clear()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cart = CartModel.objects.get(user=self.request.user)

        context["addresses"] = UserAddressModel.objects.filter(
            user=self.request.user
        )

        total_price = cart.calculate_total_price()
        context["total_price"] = total_price
        context["total_tax"] = round(total_price * Decimal("0.09"))

        return context


class ValidateCouponView(LoginRequiredMixin, HasCustomerAccessPermission, View):
    """
    فقط برای بررسی و نمایش نتیجه کوپن (AJAX)
    هیچ تغییری در دیتابیس ایجاد نمی‌کند
    """

    def post(self, request, *args, **kwargs):
        code = request.POST.get("code")
        user = request.user

        try:
            coupon = CouponModel.objects.get(code=code)
        except CouponModel.DoesNotExist:
            return JsonResponse({"message": "کد تخفیف یافت نشد"}, status=404)

        if coupon.expiration_date and coupon.expiration_date < timezone.now():
            return JsonResponse({"message": "کد تخفیف منقضی شده"}, status=403)

        if user in coupon.used_by.all():
            return JsonResponse({"message": "قبلاً استفاده شده"}, status=403)

        if coupon.used_by.count() >= coupon.max_limit_usage:
            return JsonResponse({"message": "سقف استفاده پر شده"}, status=403)

        cart = CartModel.objects.get(user=user)
        total_price = cart.calculate_total_price()

        discounted_price = round(
            total_price - (total_price * coupon.discount_percent / 100)
        )

        return JsonResponse({
            "message": "کد تخفیف معتبر است",
            "total_price": discounted_price,
            "total_tax": round(discounted_price * Decimal("0.09")),
        })


class OrderCompletedView(LoginRequiredMixin, HasCustomerAccessPermission, TemplateView):
    template_name = "order/completed.html"


class OrderFailedView(LoginRequiredMixin, HasCustomerAccessPermission, TemplateView):
    template_name = "order/failed.html"
