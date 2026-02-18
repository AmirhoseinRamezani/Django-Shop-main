# # events/tests/test_run_outbox_failur.py

# import pytest

# from events.models import OutboxEvent, OutboxStatus
# from events.services import processor


# @pytest.mark.django_db
# def test_run_outbox_failure_increments_retry(monkeypatch):
#     # Dispatch failure must increment retry and mark failed when limit reached

#     def broken_dispatch(_):
#         raise RuntimeError("SMTP DOWN")

#     monkeypatch.setattr(processor, "dispatch", broken_dispatch)

#     event = OutboxEvent.objects.create(
#         topic="user.otp",
#         payload={"email": "fail@test.com", "code": "999999"},
#         retry_count=4,
#     )

#     processor.run_outbox(max_retry=5)

#     event.refresh_from_db()

#     assert event.status == OutboxStatus.failed
#     assert event.retry_count == 5
#     assert "SMTP DOWN" in event.last_error
