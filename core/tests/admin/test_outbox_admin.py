
from django.contrib import admin

from events.admin import OutboxEventAdmin
from events.models.outbox import OutboxEvent


def test_outbox_admin_is_read_only():
    model_admin = OutboxEventAdmin(OutboxEvent, admin.site)

    assert "event_id" in model_admin.readonly_fields
    assert "status" in model_admin.readonly_fields
    assert "payload" in model_admin.readonly_fields


def test_outbox_admin_disallows_manual_creation_and_deletion(rf):
    model_admin = OutboxEventAdmin(OutboxEvent, admin.site)
    request = rf.get("/admin/events/outboxevent/")

    assert model_admin.has_add_permission(request) is False
    assert model_admin.has_delete_permission(request) is False