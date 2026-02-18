# accounts/services/jwt.py
import jwt
from django.utils import timezone
from datetime import datetime, timedelta
from django.conf import settings
from accounts.models.refresh_token import RefreshToken
from django.core.exceptions import ValidationError

ALGORITHM = "HS256"
ACCESS_TOKEN_LIFETIME = timedelta(minutes=15)
REFRESH_TOKEN_LIFETIME = timedelta(days=7)


def _now():
    return timezone.now()

def create_and_store_refresh_token(*, user_id: int) -> str:
    token = create_refresh_token(user_id=user_id)

    RefreshToken.objects.create(
        user_id=user_id,
        token=token,
        expires_at=timezone.now() + REFRESH_TOKEN_LIFETIME,
    )

    return token

def create_access_token(*, user_id: int) -> str:
    payload = {
        "type": "access",
        "user_id": user_id,
        "exp": _now() + ACCESS_TOKEN_LIFETIME,
        "iat": _now(),
    }
    return jwt.encode(payload, settings.JWT_ACCESS_SECRET, algorithm=ALGORITHM)


def create_refresh_token(*, user_id: int) -> str:
    payload = {
        "type": "refresh",
        "user_id": user_id,
        "exp": _now() + REFRESH_TOKEN_LIFETIME,
        "iat": _now(),
    }
    return jwt.encode(payload, settings.JWT_REFRESH_SECRET, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    
    try:
        # اول بدون verify امضا payload را بخوان
        unverified = jwt.decode(token, options={"verify_signature": False})
        token_type = unverified.get("type")

        if token_type == "access":
            secret = settings.JWT_ACCESS_SECRET
        elif token_type == "refresh":
            secret = settings.JWT_REFRESH_SECRET
        else:
            raise ValidationError("Invalid token type")

        return jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
        )

    except jwt.ExpiredSignatureError:
        raise ValidationError("Token expired")

    except jwt.InvalidTokenError:
        raise ValidationError("Invalid token")