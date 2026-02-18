# accounts/api/logout.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from accounts.models.refresh_token import RefreshToken


class LogoutAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        RefreshToken.objects.filter(
            user=request.user,
            is_revoked=False,
        ).update(is_revoked=True)

        return Response(
            {"detail": "Successfully logged out"},
            status=status.HTTP_200_OK,
        )
