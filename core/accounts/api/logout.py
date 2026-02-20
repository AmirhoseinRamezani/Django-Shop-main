# accounts/api/logout.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from accounts.models.refresh_token import RefreshToken


class LogoutAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        session = request.user.devicesession_set.filter(
            id=request.auth.get("session_id"),
            is_active=True,
        ).first()

        if not session:
            return Response({"detail": "Invalid session"}, status=400)

        session.is_active = False
        session.save(update_fields=["is_active"])

        RefreshToken.objects.filter(
            session=session,
            is_revoked=False,
        ).update(is_revoked=True)

        return Response({"detail": "Logged out successfully"})