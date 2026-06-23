# accounts/services/audit.py
from django.conf import settings

from accounts.models.audit_log import AuditEvent


class AuditService:

    @staticmethod
    def log(
        *,
        action,
        request=None,
        user=None,
        metadata=None,
    ):

        if not getattr(
            settings,
            "AUTH_LOG_ENABLED",
            True,
        ):
            return

        metadata = metadata or {}

        ip_address = "0.0.0.0"
        user_agent = ""

        if request:
            ip_address = (
                request.META.get("HTTP_X_FORWARDED_FOR")
                or request.META.get("REMOTE_ADDR")
                or "0.0.0.0"
            )

            user_agent = request.META.get(
                "HTTP_USER_AGENT",
                ""
            )

        AuditEvent.objects.create(
            user=user,
            action=action,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata=metadata,
        )
