# accounts/services/auth_service.py
from django.db import transaction

from django.contrib.auth import get_user_model
from accounts.services.otp_service import verify_otp

from accounts.models import OTPPurpose

User = get_user_model()

class AuthService:

    @staticmethod
    @transaction.atomic
    def verify_otp(
        *,
        email,
        code,
        purpose,
    ):
        verify_otp(
            email=email,
            code=code,
            purpose=purpose,
        )

        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "is_active": True,
                "is_verified": True,
            },
        )

        if not created and not user.is_verified:
            user.is_verified = True
            user.save(update_fields=["is_verified"])

        return user
    
    @staticmethod
    def verify_login(
        *,
        email,
        code,
    ):
        return AuthService.verify_otp(
            email=email,
            code=code,
            purpose=OTPPurpose.LOGIN,
        )


    @staticmethod
    def verify_signup(
        *,
        email,
        code,
    ):
        return AuthService.verify_otp(
            email=email,
            code=code,
            purpose=OTPPurpose.SIGNUP,
        )
        
    """
    AuthService
├── verify_otp()
├── verify_login()
└── verify_signup()

    """
    