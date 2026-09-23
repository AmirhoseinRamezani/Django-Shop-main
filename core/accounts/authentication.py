# accounts/authentication.py

from django.utils import timezone
from django.db import transaction
from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from accounts.services.jwt import decode_token
from accounts.models.device_session import DeviceSession
from django.utils.translation import gettext_lazy as _

User = get_user_model()


class JWTAuthentication(BaseAuthentication):

    def authenticate(self, request):
        header = request.headers.get("Authorization")

        if not header:
            return None

        if not header.startswith("Bearer "):
            raise AuthenticationFailed(_("Invalid authorization header"))

        token = header.split(" ", 1)[1]

        try:
            payload = decode_token(token)
        except ValidationError:
            raise AuthenticationFailed(_("Invalid or expired token"))

        if payload.get("type") != "access":
            raise AuthenticationFailed(_("Invalid token type"))

        user_id = payload.get("user_id")
        session_id = payload.get("session_id")

        if not user_id or not session_id:
            raise AuthenticationFailed(_("Invalid token payload"))

        with transaction.atomic():
            session = (
                DeviceSession.objects
                .select_for_update()
                .select_related("user")
                .filter(
                    id=session_id,
                    user_id=user_id,
                    is_active=True,
                )
                .first()
            )

            if not session:
                raise AuthenticationFailed(_("Invalid session"))

            now = timezone.now()
            if session.last_seen:
                delta = now - session.last_seen
                if delta.total_seconds() > settings.SESSION_IDLE_TIMEOUT_SECONDS:
                    session.is_active = False
                    session.revoked_at = now
                    session.save(
                        update_fields=["is_active", "revoked_at"]
                    )
                    raise AuthenticationFailed(_("Session expired"))

            session.last_seen = now
            session.save(update_fields=["last_seen"])

            request.session_obj = session

        return (session.user, None)

    def authenticate_header(self, request):
        return "Bearer"