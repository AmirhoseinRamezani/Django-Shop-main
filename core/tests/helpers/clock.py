# tests/helpers/clock.py

from contextlib import contextmanager
from unittest.mock import patch

from django.utils import timezone


@contextmanager
def freeze_time(dt):
    """
    Usage:

    with freeze_time(now):
        ...
    """

    with patch(
        "django.utils.timezone.now",
        return_value=dt,
    ):
        yield
