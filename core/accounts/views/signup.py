# accounts/views/signup.py
from django.views import View
from django.shortcuts import render, redirect
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.contrib import messages

from accounts.services.otp_service import generate_or_reuse_otp
from accounts.models import OTPPurpose

class SignupRequestOTPView(View):
    template_name = "accounts/signup_email.html"

    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        email = request.POST.get("email", "").strip().lower()

        try:
            generate_or_reuse_otp(
                email=email,
                purpose=OTPPurpose.SIGNUP,
                request=request,
            )
            request.session["otp_email"] = email
        except ValidationError:
            pass  # deliberately silent

        messages.success(
            request,
            _("If the email is valid, a verification code was sent.")
        )
        return redirect("accounts:verify-otp")
