# accounts/api/refresh_token.py
from django.core.exceptions import ValidationError

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from accounts.services.token_service import TokenService

class RefreshTokenAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        refresh = request.data.get("refresh")

        if not refresh:
            return Response(
                {"detail": "Refresh token required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            tokens = TokenService.rotate_refresh_token(
                refresh
            )
        except ValidationError:
            return Response(
                {"detail": "Invalid or expired refresh token"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        return Response(
            tokens,
            status=status.HTTP_200_OK,
        )
        