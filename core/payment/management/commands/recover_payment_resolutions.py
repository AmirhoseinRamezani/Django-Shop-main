from __future__ import annotations

import logging

from django.core.management.base import BaseCommand, CommandError

from payment.enums import PaymentStatusType
from payment.models import PaymentModel, PaymentResolution, PaymentResolutionStatus
from payment.services.verify import synchronize_successful_payment

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Recover successful payments that have not been consumed by canonical order finalization."

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=100)

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        if not 1 <= batch_size <= 1000:
            raise CommandError("--batch-size must be between 1 and 1000.")

        counts = {
            "examined": 0,
            "finalized": 0,
            "open_resolutions": 0,
            "consumed_skipped": 0,
            "errors": 0,
        }
        last_pk = 0

        # Keyset pagination advances past individual failures so one broken row
        # cannot starve later payments in this run. Failed rows remain eligible
        # for the next invocation because no durable cursor is persisted.
        while True:
            candidate_ids = list(
                PaymentModel.objects.filter(
                    pk__gt=last_pk,
                    status=PaymentStatusType.SUCCESS,
                    is_consumed=False,
                )
                .order_by("pk")
                .values_list("pk", flat=True)[:batch_size]
            )
            if not candidate_ids:
                break

            for payment_id in candidate_ids:
                last_pk = payment_id
                counts["examined"] += 1
                try:
                    current = PaymentModel.objects.only("is_consumed").get(pk=payment_id)
                    if current.is_consumed:
                        counts["consumed_skipped"] += 1
                        continue
                    payment = synchronize_successful_payment(payment_id=payment_id)
                    payment.refresh_from_db(fields=("is_consumed",))
                    if payment.is_consumed:
                        counts["finalized"] += 1
                except Exception:
                    counts["errors"] += 1
                    logger.exception(
                        "Payment resolution recovery failed for payment_id=%s",
                        payment_id,
                    )
                    self.stderr.write(f"Recovery failed for payment record {payment_id}.")
                finally:
                    if PaymentResolution.objects.filter(
                        payment_id=payment_id,
                        status=PaymentResolutionStatus.OPEN,
                    ).exists():
                        counts["open_resolutions"] += 1

        summary = " ".join(f"{key}={value}" for key, value in counts.items())
        self.stdout.write(summary)
        if counts["errors"]:
            raise CommandError(
                f"Recovery completed with {counts['errors']} error(s); rerun safely after investigation."
            )
