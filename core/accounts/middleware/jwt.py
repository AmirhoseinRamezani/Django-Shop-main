# accounts/middleware/jwt.py
from django.http import JsonResponse
from django.contrib.auth import get_user_model
from accounts.services.jwt import decode_token
from accounts.models.device_session import DeviceSession

User = get_user_model()


class JWTAuthenticationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        header = request.headers.get("Authorization")

        if not header or not header.startswith("Bearer "):
            return self.get_response(request)

        token = header.split(" ", 1)[1]

        try:
            payload = decode_token(token)

            if payload.get("type") != "access":
                raise ValueError("Invalid token type")

            user_id = payload.get("user_id")
            session_id = payload.get("session_id")

            if not session_id:
                raise ValueError("Session not bound")

            session = DeviceSession.objects.select_related("user").get(
                id=session_id,
                is_active=True,
            )

            if session.user_id != user_id:
                raise ValueError("Session mismatch")

            request.user = session.user
            session.save(update_fields=["last_seen"])

        except Exception:
            if request.path.startswith("/api/"):
                return JsonResponse(
                    {"detail": "Invalid or expired token"},
                    status=401,
                )

        return self.get_response(request)
