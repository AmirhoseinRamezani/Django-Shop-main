# accounts/api/logout_all.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from accounts.models.refresh_token import RefreshToken
from accounts.models.device_session import DeviceSession



class LogoutAllAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        sessions = DeviceSession.objects.filter(
            user=request.user,
            is_active=True,
        )

        sessions.update(is_active=False)

        RefreshToken.objects.filter(
            user=request.user,
            is_revoked=False,
        ).update(is_revoked=True)

        return Response({"detail": "Logged out from all devices"})
