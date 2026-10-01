# accounts/services/jwt.py
import jwt
import uuid 
from django.utils import timezone
from datetime import  timedelta
from django.conf import settings
from accounts.models.refresh_token import RefreshToken
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
ALGORITHM = "HS256"
ACCESS_TOKEN_LIFETIME = timedelta(minutes=15)
REFRESH_TOKEN_LIFETIME = timedelta(days=7)


def _now():
    return timezone.now()


# ------------------------
# Core Token Builders
# ------------------------

def create_access_token(*, user_id: int, session_id: str) -> str:
    payload = {
        "jti": str(uuid.uuid4()),
        "type": "access",
        "user_id": str(user_id),
        "session_id": str(session_id),
        "iat": _now(),
        "exp": _now() + ACCESS_TOKEN_LIFETIME,
    }

    return jwt.encode(
        payload,
        settings.JWT_ACCESS_SECRET,
        algorithm=ALGORITHM,
    )

def create_refresh_token(*, user_id: int, session_id: str | None = None,family_id: str | None = None,) -> str:
    payload = {
        "jti": str(uuid.uuid4()),
        "type": "refresh",
        "user_id": str(user_id),
        "session_id": str(session_id),
        "family_id": str(family_id) if family_id else None,
        "iat": _now(),
        "exp": _now() + REFRESH_TOKEN_LIFETIME,
    }

    if session_id:
        payload["session_id"] = str(session_id)

    return jwt.encode(
        payload,
        settings.JWT_REFRESH_SECRET,
        algorithm=ALGORITHM,
    )

def create_and_store_refresh_token(*, user_id: int, session, family_id=None) -> str:
    if family_id is None:
        family_id = uuid.uuid4()

    token = create_refresh_token(
        user_id=user_id,
        session_id=session.id,
        family_id=family_id,
    )

    RefreshToken.objects.create(
        user_id=user_id,
        session=session,
        token=token,
        family_id=family_id,
        expires_at=_now() + REFRESH_TOKEN_LIFETIME,
    )

    return token

# ------------------------
# Decode Logic
# ------------------------
def decode_token(token: str) -> dict:
    
    try:
        # read token type without verifying signature
        unverified = jwt.decode(
            token,
            options={"verify_signature": False},
            algorithms=[ALGORITHM],
        )
        
        token_type = unverified.get("type")

        if token_type == "access":
            secret = settings.JWT_ACCESS_SECRET
        elif token_type == "refresh":
            secret = settings.JWT_REFRESH_SECRET
        else:
            raise ValidationError(_("Invalid token type"))

        return jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
        )

    except jwt.ExpiredSignatureError:
        raise ValidationError(_("Token expired"))

    except jwt.InvalidTokenError:
        raise ValidationError(_("Invalid token"))
    

def decode_access_token(token: str):
    return jwt.decode(
        token,
        settings.JWT_ACCESS_SECRET,
        algorithms=["HS256"],
        options={
            "require": ["exp", "iat", "jti"],
        },
    )
    
def decode_refresh_token(token: str):
    return jwt.decode(
        token,
        settings.JWT_REFRESH_SECRET,
        algorithms=["HS256"],
        options={
            "require": ["exp", "iat", "jti"],
        },
    )
# ------------------------
# Facade Class (for tests & future)
# ------------------------

class JWTService:
    """
    High-level service wrapper.
    Keeps backward compatibility with functional API.
    """

    @staticmethod
    def create_access_token(user_id: int, session_id: str) -> str:
        return create_access_token(
            user_id=user_id,
            session_id=session_id,
        )

    @staticmethod
    def create_refresh_token(user_id: int, session_id: str) -> str:
        return create_refresh_token(
            user_id=user_id,
            session_id=session_id,
        )

    @staticmethod
    def decode(token: str) -> dict:
        return decode_token(token)