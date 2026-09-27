from __future__ import annotations

from tests.factories.shop import AddressFactory


class AddressBuilder:
    """Small test-only builder around AddressFactory."""

    def __init__(self):
        self.kwargs = {}

    def for_user(self, user):
        self.kwargs["user"] = user
        return self

    def build(self):
        return AddressFactory.create(**self.kwargs)
