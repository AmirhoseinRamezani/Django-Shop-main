# accounts/urls.py
from django.urls import path, include
from accounts.views.signup import SignupRequestOTPView
# from accounts.views.verify_otp import VerifyOTPView
from accounts.api.verify_otp import VerifyOTPAPIView

from accounts.views.auth import LoginView, LogoutView
# from . import views

app_name = "accounts"

urlpatterns = [
    # Web (Template-based)
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    
    path("signup/", SignupRequestOTPView.as_view(), name="signup"),
    # path("verify-otp/", VerifyOTPView.as_view(), name="verify-otp"),

    # API (REST)
    # Legacy API
    # path("api/", include("accounts.api.urls")),
    
    path("otp-verify/", VerifyOTPAPIView.as_view(), name="otp-verify"),

]
