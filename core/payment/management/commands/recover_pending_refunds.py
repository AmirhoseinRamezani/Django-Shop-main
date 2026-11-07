from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError

from payment.services.refund_recovery import RefundRecoveryWorker


class Command(BaseCommand):
    help = (
        "Reconcile one bounded batch of stale PENDING refunds using provider inquiry. "
        "This command never re-executes a refund request."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Maximum number of stale refunds to examine (1-1000).",
        )
        parser.add_argument(
            "--older-than-minutes",
            type=int,
            default=30,
            help="Only examine PENDING refunds older than this many minutes.",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        older_than_minutes = options["older_than_minutes"]

        try:
            report = RefundRecoveryWorker.run_batch(
                batch_size=batch_size,
                older_than=timedelta(minutes=older_than_minutes),
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        summary = " ".join(
            f"{field}={getattr(report, field)}"
            for field in (
                "examined",
                "succeeded",
                "failed",
                "unresolved",
                "unsupported",
                "skipped_locked",
                "errors",
            )
        )
        self.stdout.write(summary)

        if report.has_operational_failures:
            raise CommandError(
                "Refund recovery completed with operational blockers; "
                "inspect structured logs and reconcile unsupported providers manually."
            )
