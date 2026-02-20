# accounts/api/refresh_token.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.core.exceptions import ValidationError

from accounts.services.jwt import (
    decode_token,
    create_access_token,
    create_and_store_refresh_token,
)
from accounts.models.refresh_token import RefreshToken


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
            payload = decode_token(refresh)

            if payload.get("type") != "refresh":
                raise ValidationError("Invalid token type")

            session_id = payload.get("session_id")

            token_obj = RefreshToken.objects.select_related(
                "user", "session"
            ).get(token=refresh)

            if token_obj.is_revoked or token_obj.is_expired():
                # reuse detection
                token_obj.session.is_active = False
                token_obj.session.save(update_fields=["is_active"])
                raise ValidationError("Token reuse detected")

        except Exception:
            return Response(
                {"detail": "Invalid or expired refresh token"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # rotate
        token_obj.revoke()

        access = create_access_token(
            user_id=token_obj.user_id,
            session_id=token_obj.session_id,
        )

        new_refresh = create_and_store_refresh_token(
            user_id=token_obj.user_id,
            session=token_obj.session,
        )

        return Response(
            {
                "access": access,
                "refresh": new_refresh,
            },
            status=status.HTTP_200_OK,
        )
