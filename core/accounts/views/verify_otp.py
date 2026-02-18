# accounts/views/verify_otp.py  
from django.views import View
from django.shortcuts import render, redirect
from django.core.exceptions import ValidationError
from django.contrib import messages
from django.contrib.auth import login

from accounts.services.otp_service import verify_otp

class VerifyOTPView(View):
    template_name = "accounts/verify_otp.html"

    def get(self, request):
        if "otp_email" not in request.session:
            return redirect("accounts:signup-otp")
        return render(request, self.template_name)

    def post(self, request):
        email = request.POST.get("email", "").strip().lower()
        code = request.POST.get("code", "").strip()

        if not email or not code:
            messages.error(request, "جریان تایید منقضی شده است.")
            return redirect("accounts:signup-otp")
        
        try:
            user = verify_otp(email=email, code=code)
        except ValidationError as e:
            messages.error(request, str(e))
            return redirect("accounts:verify-otp")

        login(request, user)
        request.session.pop("otp_email", None)
        
        messages.success(
            request,
            "احراز هویت با موفقیت انجام شد، در حال انتقال..."
        )
        
        return redirect("website:index")
