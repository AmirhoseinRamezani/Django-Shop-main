# accounts/api/sessions.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status

from accounts.models.device_session import DeviceSession
from accounts.services.session_service import SessionService


class SessionListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        sessions = DeviceSession.objects.filter(
            user=request.user,
            is_active=True,
        ).order_by("-last_seen")

        data = [
            {
                "id": str(session.id),
                "ip_address": session.ip_address,
                "user_agent": session.user_agent,
                "created_at": session.created_at,
                "last_seen": session.last_seen,
            }
            for session in sessions
        ]

        return Response(data, status=status.HTTP_200_OK)


class SessionRevokeAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, session_id):
        try:
            session = DeviceSession.objects.get(
                id=session_id,
                user=request.user,
                is_active=True,
            )
        except DeviceSession.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        SessionService.revoke_session(session)

        return Response(status=status.HTTP_204_NO_CONTENT)


class LogoutOtherSessionsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        current_session = getattr(request, "session_obj", None)

        if not current_session:
            return Response(
                {"detail": "Session not found"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        SessionService.logout_others(
            user=request.user,
            current_session=current_session,
        )
        
        return Response(
            {"detail": "Logged out from other devices"},
            status=status.HTTP_200_OK,
        )
