# accounts/services/session_service.py
from django.db import transaction
from django.utils import timezone

from accounts.models.device_session import DeviceSession
from accounts.models.refresh_token import RefreshToken

from accounts.services.device import generate_device_hash
from accounts.services.jwt import (
    create_access_token,
    create_and_store_refresh_token,
)


class SessionService:

    @staticmethod
    def get_client_ip(request):
        return (
            getattr(request, "ip_address", None)
            or request.META.get("REMOTE_ADDR")
            or "127.0.0.1"
        )

    @staticmethod
    def get_user_agent(request):
        return request.META.get(
            "HTTP_USER_AGENT",
            "",
        )

    @classmethod
    @transaction.atomic
    def create_session(
        cls,
        *,
        request,
        user,
    ):
        ip = cls.get_client_ip(request)

        user_agent = cls.get_user_agent(request)

        device_hash = generate_device_hash(
            ip,
            user_agent,
        )

        session = DeviceSession.objects.create(
            user=user,
            device_hash=device_hash,
            ip_address=ip,
            user_agent=user_agent,
        )

        access = create_access_token(
            user_id=user.id,
            session_id=session.id,
        )

        refresh = create_and_store_refresh_token(
            user_id=user.id,
            session=session,
        )

        return {
            "session": session,
            "access": access,
            "refresh": refresh,
        }
    
    @staticmethod
    @transaction.atomic
    def revoke_session(session):
        session.is_active = False
        session.revoked_at = timezone.now()

        session.save(
            update_fields=[
                "is_active",
                "revoked_at",
            ]
        )

        RefreshToken.objects.filter(
            session=session,
            is_revoked=False,
        ).update(
            is_revoked=True,
            revoked_at=timezone.now(),
        )

    @classmethod
    @transaction.atomic
    def logout_all(cls,*,user):
        sessions = DeviceSession.objects.select_for_update().filter(
            user=user,
            is_active=True,
        )

        sessions.update(
            is_active=False,
            revoked_at=timezone.now(),
        )

        RefreshToken.objects.filter(
            session__user=user,
            is_revoked=False,
        ).update(
            is_revoked=True,
            revoked_at=timezone.now(),
        )


    @classmethod
    @transaction.atomic
    def logout_others(
        cls,
        *,
        user,
        current_session,
    ):
        sessions = (
            DeviceSession.objects
            .select_for_update()
            .filter(
                user=user,
                is_active=True,
            )
            .exclude(id=current_session.id)
        )

        ids = list(
            sessions.values_list(
                "id",
                flat=True,
            )
        )

        sessions.update(
            is_active=False,
            revoked_at=timezone.now(),
        )

        RefreshToken.objects.filter(
            session_id__in=ids,
            is_revoked=False,
        ).update(
            is_revoked=True,
            revoked_at=timezone.now(),
        )   
        
        
        
"""
SessionService
├── create_session()
├── revoke_session()
├── logout_all()
└── logout_others()
"""
