# tests/contracts/test_outbox_topics.py
import pytest

from events.dispatchers.registry import ROUTES


pytestmark = pytest.mark.django_db


def test_topics_are_unique():

    assert len(ROUTES) == len(set(ROUTES.keys()))