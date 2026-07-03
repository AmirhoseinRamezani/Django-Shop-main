# tests/concurrency/test_processor.py
import threading

import pytest

from events.services.processor import process_outbox

pytestmark = pytest.mark.django_db(transaction=True)


class TestConcurrentProcessor:

    def test_event_processed_once(
        self,
        outbox_event,
        mocker,
    ):
        dispatch = mocker.patch(
            "events.services.processor.dispatch",
        )

        t1 = threading.Thread(
            target=process_outbox,
        )

        t2 = threading.Thread(
            target=process_outbox,
        )

        t1.start()
        t2.start()

        t1.join()
        t2.join()

        outbox_event.refresh_from_db()

        assert dispatch.call_count == 1
        
        