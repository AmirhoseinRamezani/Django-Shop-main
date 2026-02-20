# accounts/middleware/jwt.py
from django.utils.deprecation import MiddlewareMixin
from rest_framework.exceptions import AuthenticationFailed

from django.contrib.auth import get_user_model
from django.http import JsonResponse

from accounts.services.jwt import decode_token

User = get_user_model()

# class JWTMiddleware(MiddlewareMixin):

#     def process_request(self, request):
#         auth = request.META.get("HTTP_AUTHORIZATION")

#         if not auth:
#             return None  # مهم: کاری نکن

#         if not auth.startswith("Bearer "):
#             return JsonResponse({"detail": "Invalid token"}, status=401)

#         token = auth.split(" ")[1]

#         try:
#             payload = decode_token(token)
#         except Exception:
#             return JsonResponse({"detail": "Invalid token"}, status=401)

#         # فقط access token قبول است
#         if payload.get("type") != "access":
#             return JsonResponse({"detail": "Invalid token type"}, status=401)

#         try:
#             user = User.objects.get(id=payload["user_id"])
#         except User.DoesNotExist:
#             return JsonResponse({"detail": "User not found"}, status=401)

#         request.user = user
        
class JWTAuthenticationMiddleware:
    """
    Attach authenticated user to request based on JWT access token.
    """

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
            request.user = User.objects.get(id=user_id)

        except Exception:
            # Just API
            if request.path.startswith("/api/"):
                return JsonResponse(
                    {"detail": "Invalid or expired token"},
                    status=401,
                )

        return self.get_response(request)
