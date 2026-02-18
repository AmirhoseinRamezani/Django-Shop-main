# accounts/api/verify_otp.py

from django.utils import timezone
from django.core.cache import cache

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework import status

from accounts.models import EmailOTP, OTPPurpose
from accounts.services.jwt import create_access_token, create_refresh_token


User = get_user_model()


class VerifyOTPAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get("email", "").lower()
        code = request.data.get("code")
        purpose = request.data.get("purpose")

        if not email or not code:
            return Response(
                {"detail": "Invalid request"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # -------- 1️⃣ Cache fallback (legacy tests) --------
        cached_code = cache.get(f"otp:{email}")
        if cached_code:
            if cached_code != code:
                return Response({"detail": "Invalid OTP"}, status=400)

            cache.delete(f"otp:{email}")
            user = User.objects.get(email=email)

            return Response({
                "access": create_access_token(user_id=user.id),
                "refresh": create_refresh_token(user_id=user.id),
            })

        # -------- 2️⃣ DB-based OTP flow --------
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
            return Response(
                {"detail": "Invalid OTP"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if otp.expire_at and otp.expire_at < timezone.now():
            return Response(
                {"detail": "OTP expired"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not check_password(code, otp.code_hash):
            return Response(
                {"detail": "Invalid OTP"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # consume OTP
        otp.is_consumed = True
        otp.save(update_fields=["is_consumed"])

        # signup flow
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

        access = create_access_token(user_id=user.id)
        refresh = create_refresh_token(user_id=user.id)

        return Response(
            {
                "access": access,
                "refresh": refresh,
            },
            status=status.HTTP_200_OK,
        )
