# accounts/services/token_service.py
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from accounts.models import RefreshToken

from accounts.services.jwt import (
    decode_token,
    create_access_token,
    create_and_store_refresh_token,
)


class TokenService:

    @classmethod
    @transaction.atomic
    def rotate_refresh_token(
        cls,
        refresh_token: str,
    ):
        payload = decode_token(refresh_token)

        if payload.get("type") != "refresh":
            raise ValidationError(
                "Invalid token type"
            )

        session_id = payload.get(
            "session_id"
        )

        token_obj = (
            RefreshToken.objects
            .select_for_update()
            .select_related(
                "user",
                "session",
            )
            .get(
                token=refresh_token
            )
        )

        if str(token_obj.session_id) != str(session_id):
            raise ValidationError(
                "Token session mismatch"
            )

        if token_obj.is_revoked or token_obj.is_expired():
            cls._handle_token_reuse(
                token_obj
            )

            raise ValidationError(
                "Token reuse detected"
            )

        token_obj.revoke()

        access = create_access_token(
            user_id=token_obj.user_id,
            session_id=token_obj.session_id,
        )

        refresh = create_and_store_refresh_token(
            user_id=token_obj.user_id,
            session=token_obj.session,
            family_id=token_obj.family_id,
        )

        return {
            "access": access,
            "refresh": refresh,
        }

    @staticmethod
    def _handle_token_reuse(
        token_obj,
    ):
        now = timezone.now()

        RefreshToken.objects.filter(
            session=token_obj.session,
            is_revoked=False,
        ).update(
            is_revoked=True,
            revoked_at=now,
        )

        session = token_obj.session

        session.is_active = False
        session.revoked_at = now

        session.save(
            update_fields=[
                "is_active",
                "revoked_at",
            ]
        )
        
# payload_family = payload.get("family_id")

# if str(payload_family) != str(token_obj.family_id):
#     raise ValidationError(
#         "Token family mismatch"
#     )