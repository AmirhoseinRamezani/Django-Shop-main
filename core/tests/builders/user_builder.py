# tests/builders/user_builder.py
from tests.factories.accounts import UserFactory

class UserBuilder:

    def __init__(self):

        self.kwargs = {}

    # --------------------------

    def admin(self):

        self.kwargs["is_staff"] = True

        return self

    # --------------------------

    def superuser(self):

        self.kwargs["is_staff"] = True
        self.kwargs["is_superuser"] = True

        return self

    # --------------------------

    def verified(self):

        self.kwargs["is_verified"] = True

        return self

    # --------------------------

    def unverified(self):

        self.kwargs["is_verified"] = False

        return self

    # --------------------------

    def build(self):

        return UserFactory(**self.kwargs)
