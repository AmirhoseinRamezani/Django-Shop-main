# tests/performance/test_outbox_processor_queries.py
import pytest

from django.db import connection
from django.test.utils import CaptureQueriesContext

from events.services.processor import process_outbox


pytestmark = pytest.mark.django_db


def test_outbox_processor_query_count(
    outbox_event,
):

    with CaptureQueriesContext(connection) as ctx:

        process_outbox()

    assert len(ctx) <= 5