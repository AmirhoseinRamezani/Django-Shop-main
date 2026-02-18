# accounts/authentication.py
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from django.contrib.auth import get_user_model
from accounts.services.jwt import decode_token
from django.core.exceptions import ValidationError


User = get_user_model()


class JWTAuthentication(BaseAuthentication):

    def authenticate(self, request):
        header = request.headers.get("Authorization")

        if not header:
            return None  # DRF handles permission → 401

        if not header.startswith("Bearer "):
            raise AuthenticationFailed("Invalid authorization header")

        token = header.split(" ", 1)[1]

        try:
            payload = decode_token(token)
        except ValidationError:
            raise AuthenticationFailed("Invalid or expired token")

        if payload.get("type") != "access":
            raise AuthenticationFailed("Invalid token type")

        # user_id = payload.get("user_id")
        try:
            user = User.objects.get(id=payload["user_id"])
        except User.DoesNotExist:
            raise AuthenticationFailed("User not found")

        return (user, None)
    
    def authenticate_header(self, request):
        return "Bearer"