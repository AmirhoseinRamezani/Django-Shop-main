from django.utils import timezone
from django.core.cache import cache
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework import status

from accounts.models import EmailOTP, OTPPurpose
from accounts.models.device_session import DeviceSession

from accounts.services.jwt import (
    create_access_token,
    create_and_store_refresh_token,
)
from accounts.services.device import generate_device_hash

User = get_user_model()


class VerifyOTPAPIView(APIView):
    permission_classes = [AllowAny]

    def _create_session_and_tokens(self, request, user):
        ip = request.META.get("HTTP_X_FORWARDED_FOR")
        if ip:
            ip = ip.split(",")[0]
        else:
            ip = request.META.get("REMOTE_ADDR", "127.0.0.1")

        user_agent = request.META.get("HTTP_USER_AGENT", "")

        device_hash = generate_device_hash(ip, user_agent)

        session = DeviceSession.objects.create(
            user=user,
            device_hash=device_hash or "legacy-test-device",
            ip_address=ip or "127.0.0.1",
            user_agent=user_agent or "legacy",
        )

        access = create_access_token(
            user_id=user.id,
            session_id=session.id,
        )

        refresh = create_and_store_refresh_token(
            user_id=user.id,
            session=session,
        )

        return access, refresh

    def post(self, request):
        email = request.data.get("email", "").lower()
        code = request.data.get("code")
        purpose = request.data.get("purpose")

        if not email or not code:
            return Response(
                {"detail": "Invalid request"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # -------- 1️⃣ Cache fallback --------
        cached_code = cache.get(f"otp:{email}")
        if cached_code:
            if cached_code != code:
                return Response({"detail": "Invalid OTP"}, status=400)

            cache.delete(f"otp:{email}")

            user = User.objects.get(email=email)

            access, refresh = self._create_session_and_tokens(request, user)

            return Response(
                {
                    "access": access,
                    "refresh": refresh,
                },
                status=status.HTTP_200_OK,
            )

        # -------- 2️⃣ DB-based flow --------
        if not purpose:
            return Response({"detail": "Purpose required"}, status=400)

        try:
            purpose_enum = OTPPurpose(purpose)
        except ValueError:
            return Response(
                {"detail": "Invalid purpose"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        otp = EmailOTP.objects.filter(
            email=email,
            purpose=purpose_enum,
            is_consumed=False,
        ).first()

        if not otp:
            return Response({"detail": "Invalid OTP"}, status=400)

        if otp.expire_at and otp.expire_at < timezone.now():
            return Response({"detail": "OTP expired"}, status=400)

        if not check_password(code, otp.code_hash):
            return Response({"detail": "Invalid OTP"}, status=400)

        otp.is_consumed = True
        otp.save(update_fields=["is_consumed"])

        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "is_active": True,
                "is_verified": True,
            },
        )

        if not created and not user.is_verified:
            user.is_verified = True
            user.save(update_fields=["is_verified"])

        access, refresh = self._create_session_and_tokens(request, user)

        return Response(
            {
                "access": access,
                "refresh": refresh,
            },
            status=status.HTTP_200_OK,
        )
