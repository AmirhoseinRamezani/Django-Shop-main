from __future__ import annotations

import hashlib
import logging
from contextlib import contextmanager
from typing import Iterator

from django.db import DatabaseError, connection
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


class RefundRecoveryLockRepository:
    """Own PostgreSQL session-level coordination for Refund recovery workers.

    Row locks are deliberately not held during provider HTTP requests. A
    session advisory lock prevents two workers from concurrently inquiring the
    same Refund after the short SKIP LOCKED selection transaction has ended.
    The lock is automatically released by PostgreSQL if the DB session dies.
    """

    @classmethod
    def ensure_supported(cls) -> None:
        if connection.vendor != "postgresql":
            raise ImproperlyConfigured(
                "Refund recovery workers require PostgreSQL advisory locks."
            )

    @staticmethod
    def _lock_key(refund_id: int) -> int:
        identity = f"django-shop:refund-recovery:{int(refund_id)}".encode()
        digest = hashlib.blake2b(identity, digest_size=8).digest()
        return int.from_bytes(digest, byteorder="big", signed=True)

    @classmethod
    @contextmanager
    def hold(cls, refund_id: int) -> Iterator[bool]:
        cls.ensure_supported()
        lock_key = cls._lock_key(refund_id)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_try_advisory_lock(%s)",
                [lock_key],
            )
            acquired = bool(cursor.fetchone()[0])

        if not acquired:
            yield False
            return

        try:
            yield True
        finally:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_advisory_unlock(%s)",
                        [lock_key],
                    )
                    released = bool(cursor.fetchone()[0])
                if not released:
                    logger.error(
                        "refund_recovery_advisory_lock_release_failed",
                        extra={"refund_id": refund_id},
                    )
                    connection.close()
            except DatabaseError:
                logger.exception(
                    "refund_recovery_advisory_lock_release_error",
                    extra={"refund_id": refund_id},
                )
                # Closing the session guarantees PostgreSQL releases its
                # session-level advisory locks.
                connection.close()
