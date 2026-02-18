# accounts/services/token_service.py

from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import login


def generate_tokens_for_user(user, request=None):
    refresh = RefreshToken.for_user(user)

    if request:
        login(request, user)

    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
    }
