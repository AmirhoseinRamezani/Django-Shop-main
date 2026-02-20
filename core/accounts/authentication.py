# accounts/authentication.py
from django.utils import timezone

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from django.contrib.auth import get_user_model
from accounts.services.jwt import decode_token
from django.core.exceptions import ValidationError

from accounts.models.device_session import DeviceSession

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

            if payload.get("type") != "access":
                raise AuthenticationFailed("Invalid token type")

            user_id = payload.get("user_id")
            session_id = payload.get("session_id")

            if not user_id or not session_id:
                raise AuthenticationFailed("Invalid token payload")
            
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                raise AuthenticationFailed("User not found")

            session = DeviceSession.objects.filter(
                id=session_id,
                user_id=user_id,
                is_active=True,
            ).first()

            if not session:
                raise AuthenticationFailed("Invalid session")
            
            session.last_seen = timezone.now()
            session.save(update_fields=["last_seen"])
            
            return (user, None)
        
        except ValidationError:
            raise AuthenticationFailed("Invalid or expired token")

    
    def authenticate_header(self, request):
        return "Bearer"