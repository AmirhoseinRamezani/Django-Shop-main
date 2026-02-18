# accounts/models/refresh_token.py
from datetime import timedelta
from django.db import models
from django.conf import settings
from django.utils import timezone


class RefreshToken(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="refresh_tokens",
    )
    token = models.CharField(max_length=512, unique=True)
    is_revoked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(fields=["token"]),
            models.Index(fields=["user", "is_revoked"]),
        ]

    def is_expired(self):
        return timezone.now() >= self.expires_at
    
    def revoke(self):
        self.is_revoked = True
        self.save(update_fields=["is_revoked"])
        
    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=30)
        super().save(*args, **kwargs)
