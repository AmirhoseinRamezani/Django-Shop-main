# accounts/views/signup.py
from django.views import View
from django.shortcuts import render, redirect
from django.core.exceptions import ValidationError
from django.contrib import messages

from accounts.services.otp_service import generate_or_reuse_otp


class SignupRequestOTPView(View):
    template_name = "accounts/signup_email.html"

    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        email = request.POST.get("email", "").strip().lower()

        try:
            generate_or_reuse_otp(email=email)
            request.session["otp_email"] = email
        except ValidationError:
            pass  # deliberately silent

        messages.success(
            request,
            "در صورت معتبر بودن ایمیل، کد تایید ارسال شد."
        )
        return redirect("accounts:verify-otp")
