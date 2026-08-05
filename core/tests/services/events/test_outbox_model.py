# tests/services/events/test_outbox_model.py
import pytest


from tests.assertions.events import (
    assert_event_pending,
    assert_event_processed,
    assert_event_failed,
)


@pytest.mark.service
@pytest.mark.django_db
class TestOutboxModel:


    def test_should_create_pending_event(
            self,
            pending_event
    ):

        assert_event_pending(
            pending_event
        )



    def test_should_create_processed_event(
            self,
            processed_event
    ):

        assert_event_processed(
            processed_event
        )



    def test_should_create_failed_event(
            self,
            failed_event
    ):

        assert_event_failed(
            failed_event
        )