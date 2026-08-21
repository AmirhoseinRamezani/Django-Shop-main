# tests/factories/accounts.py
import factory
from tests.factories.base import BaseFactory

from accounts.models import (
    UserManager,
    User,
    Profile,
    DeviceSession,
    RefreshToken,
)


from django.contrib.auth import get_user_model

# from tests.factories.shop import ProductFactory

# from tests.factories.shop import (
#     AddressFactory,
#     CouponFactory,
#     ProductFactory,
# )


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

    
    # is_active = True => status = ProductStatusType.PUBLISH
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
        # phone_number = factory.Sequence(
        #     lambda n: f"0912000{n:04}"
        # )
        
        if not create:
            return
        
        profile = self.profile
        
        if not profile.first_name:
            profile.first_name = "Test"

        if not profile.last_name:
            profile.last_name = "User"
        
        if not profile.phone_number:
            profile.phone_number = "09123456789"
        
        
        if extracted:

            for k, v in extracted.items():
                setattr(profile, k, v)

        profile.save()
    # @factory.post_generation
    # def profile(self, create, extracted, **kwargs):

    #     if not create:
    #         return

    #     profile = self.profile

    #     if not profile.phone_number:
    #         profile.phone_number = "09123456789"

    #     if not profile.first_name:
    #         profile.first_name = "Test"

    #     if not profile.last_name:
    #         profile.last_name = "User"

    #     if extracted:
    #         for k, v in extracted.items():
    #             setattr(profile, k, v)

    #     profile.save()
        
class ProfileFactory(BaseFactory):

    class Meta:
        model = Profile

    user = factory.LazyFunction(UserFactory)

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
