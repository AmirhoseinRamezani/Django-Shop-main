# accounts/api/logout.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from accounts.models.refresh_token import RefreshToken


class LogoutAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        session = getattr(request, "session_obj", None)

        if not session or not session.is_active:
            return Response(
                {"detail": "Invalid session"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        session.is_active = False
        session.save(update_fields=["is_active"])

        RefreshToken.objects.filter(
            session=session,
            is_revoked=False,
        ).update(is_revoked=True)

        return Response({"detail": "Logged out successfully"})
