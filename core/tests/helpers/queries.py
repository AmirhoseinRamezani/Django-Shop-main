# tests/helpers/queries.py
from contextlib import contextmanager

from django.db import connection
from django.test.utils import CaptureQueriesContext


@contextmanager
def capture_queries():

    with CaptureQueriesContext(connection) as ctx:
        yield ctx


def assert_max_queries(count, func, *args, **kwargs):

    with CaptureQueriesContext(connection) as ctx:
        func(*args, **kwargs)

    assert len(ctx) <= count, (
        f"{len(ctx)} queries executed (expected <= {count})"
    )