# accounts/models/refresh_token.py
import uuid
from datetime import timedelta
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.db.utils import IntegrityError


class RefreshToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="refresh_tokens",
    )
    
    session = models.ForeignKey(
        "accounts.DeviceSession",
        on_delete=models.CASCADE,
        related_name="refresh_tokens",
    )
    
    token = models.CharField(max_length=512, unique=True)
    is_revoked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    family_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    
    class Meta:
        indexes = [
            models.Index(fields=["token"]),
            models.Index(fields=["user", "is_revoked"]),
            models.Index(fields=["session"]),
            models.Index(fields=["family_id","is_revoked"]),
            models.Index(fields=["expires_at"]),
        ]
    
    def revoke(self):
        if self.is_revoked:
            return

        self.is_revoked = True
        self.revoked_at = timezone.now()
        self.save(update_fields=["is_revoked", "revoked_at"])
 
    def is_expired(self):
        return timezone.now() >= self.expires_at
           
    def save(self, *args, **kwargs):
        try:
            if not self.token:
                self.token = str(uuid.uuid4())
            if not self.expires_at:
                self.expires_at = timezone.now() + timedelta(days=30)
                
        
            super().save(*args, **kwargs)
        except IntegrityError as e:
            if "accounts_refreshtoken_token_key" in str(e):
                self.token = f"{self.token}-{uuid.uuid4()}"
                super().save(*args, **kwargs)
            else:
                raise
            
        
