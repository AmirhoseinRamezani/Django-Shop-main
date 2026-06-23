# account/api/verfy_otp.py
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework import status

from accounts.services.audit import AuditService
from accounts.api.serializers import VerifyOTPSerializer
from accounts.models import  OTPPurpose
from accounts.services.auth_service import AuthService
from accounts.services.session_service import SessionService

User = get_user_model()
class VerifyOTPAPIView(APIView):
    """
    Verify OTP and create authenticated session.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            # purpose = OTPPurpose(purpose)
            user = AuthService.verify_otp(
                email = serializer.validated_data["email"].lower(),
                code = serializer.validated_data["code"],
                purpose = serializer.validated_data["purpose"],
            )

            AuditService.log(
                action="otp_verified",
                request=request,
                user=user,
            )
            tokens = SessionService.create_session(
                request=request,
                user=user,
            )
            AuditService.log(
                action="login",
                request=request,
                user=user,
            )
        except ValidationError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "access": tokens["access"],
                "refresh": tokens["refresh"],
            },
            status=status.HTTP_200_OK,
        )