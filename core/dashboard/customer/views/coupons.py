from django.shortcuts import redirect
from django.contrib import messages
from django.views import View

from order.services.coupon import CouponService


class ApplyCouponView(View):
    def post(self, request):
        code = request.POST.get("code")

        try:
            coupon = CouponService.get_valid_coupon(code)
            request.session["coupon_id"] = coupon.id
            messages.success(request, "کد تخفیف اعمال شد")
        except Exception as e:
            messages.error(request, str(e))

        return redirect("dashboard:customer:checkout")

