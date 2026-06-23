# accounts/api/logout_all.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from accounts.services.session_service import SessionService

class LogoutAllAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        SessionService.logout_all(
            user=request.user,
        )

        return Response(
            {"detail": "Logged out from all devices"},
            status=200,
            )
