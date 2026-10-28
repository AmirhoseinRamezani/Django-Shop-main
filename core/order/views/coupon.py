# core/order/views/coupon.py
from decimal import Decimal
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.utils.translation import gettext_lazy as _
from django.views import View

from cart.cart import CartSession
from cart.models import CartModel
from order.models import CouponModel
from order.permissions import HasCustomerAccessPermission
from order.services.coupon import CouponService
from order.services.pricing import OrderPricingService

class ApplyCouponView(View):
    """Validate a coupon and store it in the session without consuming it."""


    def post(self, request, *args, **kwargs):
        code = request.POST.get("code")

        if not code:
            return JsonResponse(
                {"message": _("Discount code not entered")},
                status=400,
            )

        try:
            coupon = CouponService.get_valid_coupon(code)
        except ValidationError as exc:
            return JsonResponse({"message": exc.message}, status=400)

        request.session["coupon_id"] = coupon.id
        request.session.modified = True

        cart = CartSession(request.session)
        subtotal_price = cart.get_total_payment_amount()
        discounted_price = OrderPricingService.discounted_subtotal(
            subtotal_price,
            coupon.discount_percent,
        )
        discount_amount = Decimal(str(subtotal_price)) - discounted_price
        tax_amount = OrderPricingService.calculate_tax(
            subtotal_price=subtotal_price,
            discount_amount=discount_amount,
            shipping_price=Decimal("0"),
        )

        return JsonResponse({
            "message": _("Discount code applied"),
            "total_price": int(discounted_price),
            "total_tax": int(tax_amount),
        })

class ValidateCouponView(LoginRequiredMixin, HasCustomerAccessPermission, View):
    """Validate and preview a coupon without mutating database state."""

    def post(self, request, *args, **kwargs):
        code = request.POST.get("code")

        try:
            coupon = CouponModel.objects.get(code=code)
        except CouponModel.DoesNotExist:
            return JsonResponse({"message": "Coupon not found"}, status=404)

        if not coupon.is_valid():
            return JsonResponse({"message": "Coupon is not valid"}, status=403)

        cart = CartModel.objects.get(user=request.user)
        cart_items = list(cart.cart_items.select_related("product"))
        products = {item.product_id: item.product for item in cart_items}

        try:
            subtotal_price = OrderPricingService.calculate(cart_items, products)
        except ValidationError as exc:
            return JsonResponse({"message": exc.message}, status=400)

        discounted_price = OrderPricingService.discounted_subtotal(
            subtotal_price,
            coupon.discount_percent,
        )
        discount_amount = subtotal_price - discounted_price
        tax_amount = OrderPricingService.calculate_tax(
            subtotal_price=subtotal_price,
            discount_amount=discount_amount,
            shipping_price=Decimal("0"),
         )

        return JsonResponse({
            "message": "کد تخفیف معتبر است",
            "total_price": int(discounted_price),
            "total_tax": int(tax_amount),
        })