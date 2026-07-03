# tests/helpers/freeze.py
from contextlib import contextmanager

from freezegun import freeze_time


@contextmanager
def frozen(dt="2025-01-01 10:00:00"):
    with freeze_time(dt):
        yield