# tests/conftest.py

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from cart.models import CartItemModel, CartModel


pytest_plugins = (
    "tests.fixtures.users",
    "tests.fixtures.products",
    "tests.fixtures.coupons",
    "tests.fixtures.addresses",
    "tests.fixtures.carts",
    "tests.fixtures.orders",
    "tests.fixtures.payments",
    "tests.fixtures.events",
    "tests.fixtures.builders",
)


class _PatchProxy:
    def __init__(self, owner):
        self._owner = owner

    def __call__(self, target, *args, **kwargs):
        patcher = patch(
            target,
            *args,
            **kwargs,
        )

        mocked = patcher.start()
        self._owner._patchers.append(patcher)

        return mocked

    def object(self, target, attribute, *args, **kwargs):
        patcher = patch.object(
            target,
            attribute,
            *args,
            **kwargs,
        )

        mocked = patcher.start()
        self._owner._patchers.append(patcher)

        return mocked


class _Mocker:
    def __init__(self):
        self._patchers = []
        self.patch = _PatchProxy(self)

    def Mock(self, *args, **kwargs):
        return Mock(*args, **kwargs)

    def stopall(self):
        while self._patchers:
            self._patchers.pop().stop()


@pytest.fixture(autouse=True)
def cart_model_compatibility(monkeypatch):
    """Keep legacy test scenarios compatible with the current DB cart model."""
    def add(self, product, quantity=1):
        item, created = CartItemModel.objects.get_or_create(
            cart=self,
            product=product,
            defaults={"quantity": quantity},
        )
        if not created:
            item.quantity += quantity
            item.save(update_fields=["quantity", "updated_date"])
        return item

    monkeypatch.setattr(CartModel, "add", add, raising=False)


@pytest.fixture
def mocker():
    helper = _Mocker()

    try:
        yield helper
    finally:
        helper.stopall()