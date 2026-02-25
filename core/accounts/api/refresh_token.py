# accounts/api/refresh_token.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
import uuid
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.services.jwt import (
    decode_token,
    create_access_token,
    create_and_store_refresh_token,
)
from accounts.models.refresh_token import RefreshToken


class RefreshTokenAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    @transaction.atomic
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
            
            token_obj = RefreshToken.objects.select_for_update().select_related(
                "user", "session"
            ).get(token=refresh)
            
            if str(token_obj.session_id) != str(session_id):
                raise ValidationError("Token session mismatch")
            
            if token_obj.is_revoked or token_obj.is_expired():
                now = timezone.now()

                # kill whole token family
                RefreshToken.objects.filter(
                    session=token_obj.session,
                    is_revoked=False,
                ).update(
                    is_revoked=True,
                    revoked_at=now,
                )

                # deactivate device session
                session = token_obj.session
                session.is_active = False
                session.revoked_at = now
                session.save(update_fields=["is_active", "revoked_at"])
                
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

        # family_id = uuid.uuid4()
        family_id = token_obj.family_id
        new_refresh = create_and_store_refresh_token(
            user_id=token_obj.user_id,
            session=token_obj.session,
            family_id=family_id,
        )

        return Response(
            {
                "access": access,
                "refresh": new_refresh,
            },
            status=status.HTTP_200_OK,
        )
