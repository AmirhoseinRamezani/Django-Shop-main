# accounts/models/otp.py
from django.db import models
from django.utils import timezone
from django.conf import settings
from django.core.exceptions import ValidationError
from django.contrib.auth.hashers import check_password

class OTPPurpose(models.TextChoices):
    SIGNUP = "signup", "Signup"
    LOGIN = "login", "Login"


MAX_VERIFY_ATTEMPTS = 5

class EmailOTP(models.Model):
    email = models.EmailField(db_index=True)

    code_hash = models.CharField(max_length=4)

    purpose = models.CharField(
        max_length=20,
        choices=OTPPurpose.choices,
        default=OTPPurpose.SIGNUP,
        db_index=True,
    )

    is_consumed = models.BooleanField(default=False)

    expire_at = models.DateTimeField()

    created_date = models.DateTimeField(auto_now_add=True)
    consumed_date = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        indexes = [
            models.Index(fields=["email", "purpose", "is_consumed"]),
        ]
        ordering = ["-created_date"]
        
    def is_expired(self) -> bool:
        return timezone.now() >= self.expire_at
    
    def verify(self, raw_code: str):

        if self.is_expired():
            raise ValidationError("OTP expired")

        if self.attempts >= MAX_VERIFY_ATTEMPTS:
            raise ValidationError("Too many failed attempts")

        if not check_password(raw_code, self.code_hash):
            self.attempts += 1
            self.save(update_fields=["attempts"])
            raise ValidationError("Invalid code")
        
        
        self.is_consumed = True
        self.consumed_date = timezone.now()
        self.save(update_fields=["is_consumed", "consumed_date"])

    def __str__(self):
        return f"{self.email} | {self.purpose} | consumed={self.is_consumed}"