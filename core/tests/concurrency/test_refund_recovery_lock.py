from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from django.db import close_old_connections

from payment.repositories.refund_recovery_lock_repository import (
    RefundRecoveryLockRepository,
)

pytestmark = pytest.mark.django_db(transaction=True)


def test_postgres_advisory_lock_allows_only_one_worker_per_refund():
    refund_id = 987654321
    first_acquired = Event()
    release_first = Event()

    def first_worker():
        close_old_connections()
        try:
            with RefundRecoveryLockRepository.hold(refund_id) as acquired:
                first_acquired.set()
                assert acquired is True
                assert release_first.wait(timeout=10)
                return acquired
        finally:
            close_old_connections()

    def second_worker():
        close_old_connections()
        try:
            assert first_acquired.wait(timeout=10)
            with RefundRecoveryLockRepository.hold(refund_id) as acquired:
                return acquired
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(first_worker)
        second = executor.submit(second_worker)
        assert second.result(timeout=10) is False
        release_first.set()
        assert first.result(timeout=10) is True
