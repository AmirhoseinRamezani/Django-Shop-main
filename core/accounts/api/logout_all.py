# accounts/api/logout_all.py
from django.utils import timezone
from django.db import transaction

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from accounts.models.refresh_token import RefreshToken
from accounts.models.device_session import DeviceSession



class LogoutAllAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        
        # deactivate all active sessions
        sessions = DeviceSession.objects.select_for_update().filter(
            user=request.user,
            is_active=True,
        )

        sessions.update(
            is_active=False,
            revoked_at=timezone.now(),
        )

        # revoke all refresh tokens of those sessions
        RefreshToken.objects.select_for_update().filter(
            session__user=request.user,
            is_revoked=False,
        ).update(
            is_revoked=True,
            revoked_at=timezone.now(),
        )

        return Response({"detail": "Logged out from all devices"})
