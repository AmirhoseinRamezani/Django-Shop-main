# accounts/api/views.py

from rest_framework.views import APIView
from rest_framework.response import Response

from rest_framework import status
from accounts.models import OTPPurpose
from django.core.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from accounts.services.audit import AuditService
from accounts.services.otp_service import generate_or_reuse_otp

from accounts.api.serializers import RequestOTPSerializer
from accounts.exceptions import OTPThrottleException

class RequestOTPAPIView (APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RequestOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"].lower()
        purpose = serializer.validated_data["purpose"]

        try:
            
            generate_or_reuse_otp(
                email=email,
                purpose=purpose,
                request=request,
            )
            AuditService.log(
                action="otp_requested",
                request=request,
                metadata={
                    "email": email,
                    "purpose": purpose,
                }
            )
            
        except OTPThrottleException as e:
            return Response(
                {"detail": str(e)},
                status=429
            )
        except ValidationError as e:
            return Response(
                {"detail": str(e)},
                status=400
            )
        
        return Response(
            {"detail": "If the email is valid, the code will be sent."},
            status=status.HTTP_200_OK,
        )