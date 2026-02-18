# accounts/api/urls.py
from django.urls import path
from accounts.api.views import RequestOTPAPIView
from accounts.api.verify_otp import VerifyOTPAPIView
from accounts.api.me import MeAPIView
from accounts.api.refresh_token import RefreshTokenAPIView
from accounts.api.logout import LogoutAPIView
from accounts.api.login import LoginAPIView

app_name = "accounts-api"

urlpatterns = [
    path("otp/request/", RequestOTPAPIView.as_view(), name="otp-request"),
    path("otp/verify/", VerifyOTPAPIView.as_view(), name="otp-verify"),
    path("token/refresh/", RefreshTokenAPIView.as_view(), name="token-refresh"),
    path("logout/", LogoutAPIView.as_view(), name="logout"),
    path("login/", LoginAPIView.as_view(), name="login"),
    # path("signup/otp/", SignupOTPView.as_view(), name="signup-otp"),
    path("me/", MeAPIView.as_view(), name="me"),
    
]