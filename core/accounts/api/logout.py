# accounts/api/logout.py

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from accounts.services.audit import AuditService
from accounts.services.session_service import SessionService

class LogoutAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        session = getattr(request, "session_obj", None)

        if not session:
            return Response(
                {"detail": "Invalid session"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        SessionService.revoke_session(session)
        AuditService.log(
            action="logout",
            request=request,
            user=request.user,
        )
        return Response(
            {"detail": "Logged out successfully"},
            status=200,
            )
