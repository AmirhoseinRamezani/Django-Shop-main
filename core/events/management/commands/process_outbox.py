# events/management/commands/process_outbox.py

from django.core.management.base import BaseCommand
from events.processor import process_outbox


class Command(BaseCommand):
    help = "Process Outbox events"

    def handle(self, *args, **options):
        process_outbox()
