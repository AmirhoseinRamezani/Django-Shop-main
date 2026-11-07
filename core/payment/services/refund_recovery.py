from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from payment.enums import RefundStatus
from payment.exceptions import PaymentGatewayNotSupportedError
from payment.repositories.refund_recovery_lock_repository import (
    RefundRecoveryLockRepository,
)
from payment.repositories.refund_repository import RefundRepository
from payment.services.refund import RefundService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RefundRecoveryReport:
    examined: int = 0
    succeeded: int = 0
    failed: int = 0
    unresolved: int = 0
    unsupported: int = 0
    skipped_locked: int = 0
    errors: int = 0

    @property
    def has_operational_failures(self) -> bool:
        return bool(self.errors or self.unsupported)


class RefundRecoveryWorker:
    """Process one bounded batch of stale PENDING Refunds.

    Selection uses SKIP LOCKED in a short transaction. Provider inquiry and
    finalization are delegated to RefundService after that transaction ends.
    A PostgreSQL advisory lock serializes workers per Refund without retaining
    row locks across network I/O. This worker never invokes GatewayService.refund.
    """

    MIN_BATCH_SIZE = 1
    MAX_BATCH_SIZE = 1000
    MIN_AGE = timedelta(minutes=1)
    MAX_AGE = timedelta(days=365)

    @classmethod
    def run_batch(
        cls,
        *,
        batch_size: int = 100,
        older_than: timedelta = timedelta(minutes=30),
        now: datetime | None = None,
    ) -> RefundRecoveryReport:
        cls._validate_options(
            batch_size=batch_size,
            older_than=older_than,
        )
        RefundRecoveryLockRepository.ensure_supported()

        current_time = now or timezone.now()
        requested_before = current_time - older_than

        # Evaluate the locked queryset inside this transaction. The row locks
        # are released before any gateway inquiry starts.
        with transaction.atomic():
            candidate_ids = list(
                RefundRepository.stale_pending_for_update_skip_locked(
                    requested_before=requested_before,
                ).values_list("pk", flat=True)[:batch_size]
            )

        counts = {
            "examined": 0,
            "succeeded": 0,
            "failed": 0,
            "unresolved": 0,
            "unsupported": 0,
            "skipped_locked": 0,
            "errors": 0,
        }

        for refund_id in candidate_ids:
            counts["examined"] += 1

            try:
                with RefundRecoveryLockRepository.hold(refund_id) as acquired:
                    if not acquired:
                        counts["skipped_locked"] += 1
                        logger.info(
                            "refund_recovery_skipped_locked",
                            extra={"refund_id": refund_id},
                        )
                        continue

                    refund = RefundService.reconcile_pending_refund(
                        refund_id=refund_id,
                    )

                if refund.status == RefundStatus.SUCCESS:
                    counts["succeeded"] += 1
                elif refund.status == RefundStatus.FAILED:
                    counts["failed"] += 1
                else:
                    counts["unresolved"] += 1

                logger.info(
                    "refund_recovery_record_processed",
                    extra={
                        "refund_id": refund_id,
                        "refund_status": str(refund.status),
                    },
                )

            except PaymentGatewayNotSupportedError:
                counts["unsupported"] += 1
                logger.warning(
                    "refund_recovery_inquiry_unsupported",
                    extra={"refund_id": refund_id},
                )
            except Exception:
                counts["errors"] += 1
                logger.exception(
                    "refund_recovery_record_failed",
                    extra={"refund_id": refund_id},
                )

        report = RefundRecoveryReport(**counts)
        logger.info(
            "refund_recovery_batch_completed",
            extra={
                field: getattr(report, field)
                for field in counts
            },
        )
        return report

    @classmethod
    def _validate_options(
        cls,
        *,
        batch_size: int,
        older_than: timedelta,
    ) -> None:
        if not cls.MIN_BATCH_SIZE <= batch_size <= cls.MAX_BATCH_SIZE:
            raise ValueError(
                f"batch_size must be between {cls.MIN_BATCH_SIZE} "
                f"and {cls.MAX_BATCH_SIZE}."
            )

        if not cls.MIN_AGE <= older_than <= cls.MAX_AGE:
            raise ValueError(
                "older_than must be between one minute and 365 days."
            )
