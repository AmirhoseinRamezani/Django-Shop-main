# accounts/services/audit.py
from accounts.models.audit_log import AuditEvent


def log_event(request, action, user=None, **metadata):
    AuditEvent.objects.create(
        user=user,
        action=action,
        ip_address=getattr(request, "ip_address", None),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
        metadata=metadata,
    )
