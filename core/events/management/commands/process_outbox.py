# events/management/commands/process_outbox.py

from django.core.management.base import BaseCommand, CommandError
from events.services.processor import process_outbox


class Command(BaseCommand):
    help = "Claim and dispatch pending transactional outbox events."

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=50)
        parser.add_argument("--max-retry", type=int, default=5)
        parser.add_argument("--lease-seconds", type=int, default=300)
        parser.add_argument("--retry-base-seconds", type=int, default=5)
        parser.add_argument("--retry-max-seconds", type=int, default=900)

    def handle(self, *args, **options):
        try:
            result = process_outbox(
                batch_size=options["batch_size"],
                max_retry=options["max_retry"],
                lease_seconds=options["lease_seconds"],
                retry_base_seconds=options["retry_base_seconds"],
                retry_max_seconds=options["retry_max_seconds"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                "Outbox: "
                f"claimed={result.claimed}, "
                f"processed={result.processed}, "
                f"retried={result.retried}, "
                f"failed={result.failed}, "
                f"lost_claims={result.lost_claims}"
            )
        )