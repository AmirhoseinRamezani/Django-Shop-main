# accounts/middleware/jwt.py
from django.contrib.auth.models import AnonymousUser
from accounts.services.jwt import decode_token
from accounts.models.device_session import DeviceSession
# from django.utils import timezone

# User = get_user_model()

class JWTAuthenticationMiddleware:
    
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        
        # if request.path.startswith("/api/"):
        #     return self.get_response(request)

        header = request.headers.get("Authorization")

        if not header or not header.startswith("Bearer "):
            return self.get_response(request)

        token = header.split(" ", 1)[1]

        try:
            payload = decode_token(token)

            if payload.get("type") != "access":
                return self.get_response(request)

            session = DeviceSession.objects.select_related("user").get(
                id=payload.get("session_id"),
                is_active=True,
            )

            request.user = session.user
            request.session_obj = session

        except Exception:
            request.user = AnonymousUser()

        return self.get_response(request)