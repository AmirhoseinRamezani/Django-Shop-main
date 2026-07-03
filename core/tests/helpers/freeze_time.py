# tests/helpers/freeze_time.py
from contextlib import contextmanager

from freezegun import freeze_time


@contextmanager
def frozen(date):

    with freeze_time(date):
        yield