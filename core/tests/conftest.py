# tests/conftest.py

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