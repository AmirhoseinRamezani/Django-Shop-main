# tests/contracts/test_fixtures_contract.py
import importlib


MODULES = (
    "tests.fixtures.users",
    "tests.fixtures.products",
    "tests.fixtures.orders",
    "tests.fixtures.payments",
    "tests.fixtures.events",
    "tests.fixtures.builders",
)


def test_fixture_modules_import():

    for module in MODULES:

        assert importlib.import_module(module)