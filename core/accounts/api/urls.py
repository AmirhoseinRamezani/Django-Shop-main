# accounts/api/urls.py
from django.urls import path
from accounts.api.views import RequestOTPAPIView
from accounts.api.verify_otp import VerifyOTPAPIView
from accounts.api.me import MeAPIView
from accounts.api.refresh_token import RefreshTokenAPIView
from accounts.api.logout import LogoutAPIView
# from accounts.api.login import LoginAPIView
from accounts.api.logout_all import LogoutAllAPIView
from accounts.api.sessions import (
    SessionListAPIView,
    SessionRevokeAPIView,
    LogoutOtherSessionsAPIView,
)

app_name = "accounts-api"

urlpatterns = [
    path("otp/request/", RequestOTPAPIView.as_view(), name="otp-request"),
    path("otp/verify/", VerifyOTPAPIView.as_view(), name="otp-verify"),
    path("token/refresh/", RefreshTokenAPIView.as_view(), name="token-refresh"),
    path("logout/", LogoutAPIView.as_view(), name="logout"),
    # path("login/", LoginAPIView.as_view(), name="login"),
    # path("signup/otp/", SignupOTPView.as_view(), name="signup-otp"),
    path("me/", MeAPIView.as_view(), name="me"),
    
    path("sessions/", SessionListAPIView.as_view(), name="session-list"),
    path(
        "sessions/<uuid:session_id>/",
        SessionRevokeAPIView.as_view(),
        name="session-revoke",
    ),
    path(
        "sessions/logout-others/",
        LogoutOtherSessionsAPIView.as_view(),
        name="logout-others",
    ),
    path("logout/all/", LogoutAllAPIView.as_view(), name="logout-all"),
]