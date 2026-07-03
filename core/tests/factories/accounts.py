# tests/factories/accounts.py
import factory

from django.contrib.auth import get_user_model

from accounts.models import (
    User,
    Profile,
    DeviceSession,
    RefreshToken,
)

from tests.base import BaseFactory

User = get_user_model()

class UserFactory(BaseFactory):

    class Meta:
        model = User

    email = factory.Sequence(
        lambda n: f"user{n}@test.com"
    )
    # username = factory.Sequence(
    #     lambda n: f"user{n}"
    # )

    # email = factory.LazyAttribute(
    #     lambda o: f"{o.username}@test.com"
    # )

    # phone = factory.Sequence(
    #     lambda n: f"0912000{n:04}"
    # )

    password = factory.PostGenerationMethodCall(
        "set_password",
        "password123",
    )

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

        inactive = factory.Trait(
            is_active=False,
        )

        unverified = factory.Trait(
            is_verified=False,
        )
        
class ProfileFactory(BaseFactory):

    class Meta:
        model = Profile

    user = factory.SubFactory(UserFactory)

    first_name = factory.Faker("first_name")

    last_name = factory.Faker("last_name")

    phone_number = "09123456789"


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
