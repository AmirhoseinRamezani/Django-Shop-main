# tests/factories/accounts.py
import factory
from tests.factories.base import BaseFactory

from accounts.models import (
    Profile,
    DeviceSession,
    RefreshToken,
)

from django.contrib.auth import get_user_model


User = get_user_model()

class UserFactory(BaseFactory):

    class Meta:
        model = User
        skip_postgeneration_save = True

    email = factory.Sequence(
        lambda n: f"user{n}@test.com"
    )

    @factory.post_generation
    def password(self, create, extracted, **kwargs):
        """Set user password properly after creation."""
        raw_password = extracted or "password123"
        self.set_password(raw_password)
        if create:
            self.save(update_fields=["password"])

    is_staff = False
    is_superuser = False
    is_active = True
    is_verified = True

    class Params:

        admin = factory.Trait(
            is_staff=True,
        )

        superuser = factory.Trait(
            is_staff=True,
            is_superuser=True,
        )

        unverified = factory.Trait(
            is_verified=False,
        )
        
    @factory.post_generation
    def profile(self, create, extracted, **kwargs):
        """
        Populate defaults on the auto-generated profile created by post_save signal.
        Supports both build() and create() strategies seamlessly.
        """
        if not create:
            # حالت build: سیگنال اجرا نشده، پس Profile را به صورت build به کاربر متصل می‌کنیم
            profile_instance = ProfileFactory.build(user=self)
            if extracted and isinstance(extracted, dict):
                for key, val in extracted.items():
                    setattr(profile_instance, key, val)
            self.profile = profile_instance
            return

        # حالت create: profile توسط سیگنال post_save ساخته شده است
        user_profile = getattr(self, "profile", None)
        if not user_profile:
            return

        updated = False

        # Apply default mock values if empty
        if not user_profile.first_name:
            user_profile.first_name = "Test"
            updated = True
        if not user_profile.last_name:
            user_profile.last_name = "User"
            updated = True
        if not user_profile.phone_number:
            user_profile.phone_number = "09123456789"
            updated = True

        # Apply explicitly passed dictionary profile overrides
        if extracted and isinstance(extracted, dict):
            for key, val in extracted.items():
                setattr(user_profile, key, val)
            updated = True

        if updated:
            user_profile.save()
        
class ProfileFactory(BaseFactory):
    """
    Factory for Profile model.
    Utilizes UserFactory and updates the signal-created profile instance.
    """
    class Meta:
        model = Profile
        skip_postgeneration_save = True

    user = factory.SubFactory(UserFactory)
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    phone_number = "09123456789"
    
    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        """
        Prevent Duplicate Key IntegrityError caused by Django post_save signal.
        The user creation fires signal -> Profile.objects.create(user=user).
        We catch that profile and update its attributes.
        """
        user = kwargs.pop("user", None)
        if user is None:
            user = UserFactory.create()

        # Get or create safety net
        profile, _ = model_class.objects.get_or_create(user=user)

        for attr, value in kwargs.items():
            setattr(profile, attr, value)

        profile.save()
        return profile

class DeviceSessionFactory(BaseFactory):

    class Meta:
        model = DeviceSession

    user = factory.SubFactory(UserFactory)

    device_hash = factory.Faker("uuid4")

    ip_address = "127.0.0.1"

    user_agent = "pytest"


class RefreshTokenFactory(BaseFactory):

    class Meta:
        model = RefreshToken

    user = factory.SubFactory(UserFactory)

    session = factory.SubFactory(DeviceSessionFactory)

    token = factory.Faker("uuid4")
    
# UserFactory
# ProfileFactory    
# import factory
