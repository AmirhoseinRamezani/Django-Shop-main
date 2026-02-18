# accounts/models/audit_log.py
from django.db import models
from django.conf import settings


class AuditEvent(models.Model):
    ACTION_CHOICES = [
        ("otp_requested", "OTP Requested"),
        ("otp_verified", "OTP Verified"),
        ("otp_failed", "OTP Failed"),
        ("login", "Login"),
        ("logout", "Logout"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField(blank=True)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["action", "created_at"]),
            models.Index(fields=["ip_address"]),
        ]
