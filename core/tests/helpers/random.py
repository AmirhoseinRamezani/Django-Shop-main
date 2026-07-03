# tests/helpers/random.py
import random


def seed(value=12345):
    """
    Deterministic random for tests.
    """

    random.seed(value)