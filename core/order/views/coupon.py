from django.views import View
from django.http import JsonResponse
from decimal import Decimal
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from order.permissions import HasCustomerAccessPermission
from django.contrib.sessions.backends.base import SessionBase
from django.core.exceptions import ValidationError
from order.models import CouponModel
from order.services.coupon import CouponService
from cart.cart import CartSession
from cart.models import CartModel

from django.utils.translation import gettext_lazy as _
class ApplyCouponView(View):
    """
    Validate coupon and store it in session (NO consumption here)
    """

    def post(self, request, *args, **kwargs):
        code = request.POST.get("code")

        if not code:
            return JsonResponse(
                {"message": _("Discount code not entered")},
                status=400
            )

        try:
            coupon = CouponService.get_valid_coupon(code)
        except ValidationError as e:
            return JsonResponse(
                {"message": e.message},
                status=400
            )

        # Store coupon id in session
        request.session["coupon_id"] = coupon.id
        request.session.modified = True

        # Recalculate cart prices
        cart = CartSession(request.session)
        total_price = cart.get_total_payment_amount()

        discounted_price = int(
            total_price * (100 - coupon.discount_percent) / 100
        )

        # Example tax (keep consistent with your logic)
        total_tax = int(discounted_price * 0.09)

        return JsonResponse({
            "message": _("Discount code applied"),
            "total_price": discounted_price,
            "total_tax": total_tax
        })

class ValidateCouponView(LoginRequiredMixin, HasCustomerAccessPermission, View):
    """
    Only for checking and displaying coupon result (AJAX)
    Does not make any changes to the database
    """
    def post(self, request, *args, **kwargs):
        code = request.POST.get("code")

        try:
            coupon = CouponModel.objects.get(code=code)
        except CouponModel.DoesNotExist:
            return JsonResponse({"message": "Coupon not found"}, status=404)

        # Centralized validation from model
        if not coupon.is_valid():
            return JsonResponse({"message": "Coupon is not valid"}, status=403)

        cart = CartModel.objects.get(user=request.user)
        total_price = cart.calculate_total_price()

        discounted_price = round(
            total_price - (total_price * coupon.discount_percent / 100)
        )

        return JsonResponse({
            "message": "کد تخفیف معتبر است",
            "total_price": discounted_price,
            "total_tax": round(discounted_price * Decimal("0.09")),
        })