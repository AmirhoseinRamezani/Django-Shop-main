from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db.models import QuerySet

from payment.enums import PaymentStatusType
from payment.models import PaymentModel
from payment.services.verify import synchronize_successful_payment


class Command(BaseCommand):
    help = (
        "Recover verified successful Payments that have not yet been "
        "consumed by their Orders."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Maximum number of Payments to process (default: 100).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only report eligible Payments without processing them.",
        )

    @staticmethod
    def get_candidates(*, limit: int) -> QuerySet:
        """
        Discover candidates without acquiring row locks.

        The synchronization service owns the canonical lock order:
            Order -> Payment -> PaymentAttempt

        Payments with a PaymentResolution are intentionally excluded.
        They require the existing resolution/reconciliation workflow,
        not blind automatic finalization.
        """
        return (
            PaymentModel.objects
            .filter(
                status=PaymentStatusType.SUCCESS,
                is_consumed=False,
                resolution__isnull=True,
            )
            .order_by("created_date", "pk")
            .values_list("pk", flat=True)[:limit]
        )

    def handle(self, *args, **options) -> None:
        limit = options["limit"]

        if limit < 1:
            raise CommandError("--limit must be greater than zero.")

        payment_ids = list(self.get_candidates(limit=limit))

        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run: {len(payment_ids)} successful Payment(s) "
                    "eligible for recovery."
                )
            )
            return

        recovered = 0
        skipped = 0
        errors = 0

        for payment_id in payment_ids:
            try:
                payment = synchronize_successful_payment(
                    payment_id=payment_id,
                )
            except Exception as exc:
                errors += 1
                self.stderr.write(
                    self.style.ERROR(
                        f"Payment #{payment_id}: recovery failed "
                        f"({type(exc).__name__})."
                    )
                )
                continue

            if payment.is_consumed:
                recovered += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Payment #{payment_id}: recovered."
                    )
                )
            else:
                # A recognized terminal Order conflict is recorded as a
                # PaymentResolution by the canonical service.
                skipped += 1
                self.stdout.write(
                    f"Payment #{payment_id}: not consumed; "
                    "requires resolution."
                )

        self.stdout.write(
            self.style.SUCCESS(
                "Recovery finished: "
                f"checked={len(payment_ids)}, "
                f"recovered={recovered}, "
                f"skipped={skipped}, "
                f"errors={errors}."
            )
        )