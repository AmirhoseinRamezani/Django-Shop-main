# accounts/models/device_session.py
import uuid
from django.db import models
from django.conf import settings
from django.db.models import Q
from django.utils import timezone


class DeviceSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="device_sessions",
    )

    device_hash = models.CharField(max_length=128)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    is_active = models.BooleanField(default=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        indexes = [
            models.Index(fields=["user", "device_hash"]),
            models.Index(
                fields=[
                    "user",
                    "is_active",
                ],
            ),
        ]
        
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        is_active=True,
                        revoked_at__isnull=True,
                    )
                    |
                    Q(
                        is_active=False,
                        revoked_at__isnull=False,
                    )
                ),
                name="device_session_active_revocation_consistent",
            ),
        ]
        
    def revoke(self):
        if not self.is_active:
            return

        self.is_active = False
        self.revoked_at = timezone.now()

        self.save(
            update_fields=[
                "is_active",
                "revoked_at",
            ]
        )
        
