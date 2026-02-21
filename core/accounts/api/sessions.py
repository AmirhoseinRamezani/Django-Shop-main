# accounts/api/sessions.py

from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status

from accounts.models.refresh_token import RefreshToken
from accounts.models.device_session import DeviceSession


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

    @transaction.atomic
    def delete(self, request, session_id):
        try:
            session = DeviceSession.objects.select_for_update().get(
                id=session_id,
                user=request.user,
                is_active=True,
            )
        except DeviceSession.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        session.is_active = False
        session.save(update_fields=["is_active"])

        RefreshToken.objects.filter(
            session=session,
            is_revoked=False,
        ).update(is_revoked=True)

        return Response(status=status.HTTP_204_NO_CONTENT)


class LogoutOtherSessionsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        current_session = getattr(request, "session_obj", None)

        if not current_session:
            return Response(
                {"detail": "Session not found"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        other_sessions = list(
            DeviceSession.objects
            .select_for_update()
            .filter(
                user=request.user,
                is_active=True,
            )
            .exclude(id=current_session.id)
        )

        if not other_sessions:
            return Response(
                {"detail": "No other active sessions"},
                status=status.HTTP_200_OK,
            )

        session_ids = [s.id for s in other_sessions]

        DeviceSession.objects.filter(
            id__in=session_ids
        ).update(is_active=False)

        RefreshToken.objects.filter(
            session__id__in=session_ids,
            is_revoked=False,
        ).update(is_revoked=True)

        return Response(
            {"detail": "Logged out from other devices"},
            status=status.HTTP_200_OK,
        )
