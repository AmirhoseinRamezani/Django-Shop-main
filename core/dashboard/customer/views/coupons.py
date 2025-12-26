from django.shortcuts import redirect
from django.contrib import messages
from django.views import View
from cart.cart import CartSession

from order.services.coupon import CouponService
from django.core.exceptions import ValidationError

class ApplyCouponView(View):
    def post(self, request):
        code = request.POST.get("code").strip()
        cart = CartSession(request.session)
        
        if not code:
            cart.remove_coupon()
            messages.info(request, "کد تخفیف حذف شد")
            return redirect(request.META.get("HTTP_REFERER"))

        try:
            CouponService.get_valid_coupon(code)
            cart.set_coupon(code)
            messages.success(request, "کد تخفیف اعمال شد")
        except ValidationError as e:
            cart.remove_coupon()
            messages.error(request, e.message)

        return redirect("dashboard:customer:checkout")

