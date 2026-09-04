# tests/payment/repositories/test_gateway_log_repository.py

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from payment.enums import GatewayLogType
from payment.repositories.gateway_log_repository import GatewayLogRepository
from tests.factories.payment import GatewayLogFactory, PaymentAttemptFactory, RefundFactory


@pytest.mark.django_db
class TestGatewayLogRepository:
    def test_basic_reads_and_attempt_scope(self):
        attempt = PaymentAttemptFactory()
        log = GatewayLogFactory(attempt=attempt)

        assert GatewayLogRepository.get(log.pk).pk == log.pk
        assert list(GatewayLogRepository.for_attempt(attempt.pk)) == [log]
        assert GatewayLogRepository.latest_for_attempt(attempt.pk).pk == log.pk

    def test_refund_scope_and_latest(self):
        refund = RefundFactory()
        log = GatewayLogFactory(attempt=None, refund=refund, log_type=GatewayLogType.REFUND)

        assert list(GatewayLogRepository.for_refund(refund.pk)) == [log]
        assert GatewayLogRepository.latest_for_refund(refund.pk).pk == log.pk

    def test_exactly_one_owner_is_database_authority(self):
        attempt = PaymentAttemptFactory()
        refund = RefundFactory()

        with pytest.raises(ValidationError):
            GatewayLogRepository.create(
                attempt=None,
                refund=None,
                gateway="zarinpal",
                log_type=GatewayLogType.REQUEST,
                direction="outbound",
            )

        with pytest.raises(ValidationError):
            GatewayLogRepository.create(
                attempt=attempt,
                refund=refund,
                gateway="zarinpal",
                log_type=GatewayLogType.REQUEST,
                direction="outbound",
            )

        from payment.models import GatewayLog

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                GatewayLog.objects.bulk_create([
                    GatewayLog(
                        attempt=None,
                        refund=None,
                        gateway="zarinpal",
                        log_type=GatewayLogType.REQUEST,
                        direction="outbound",
                    ),
                ])

    def test_audit_queries_do_not_treat_gateway_success_as_financial_truth(self):
        log = GatewayLogFactory(is_success=True)

        assert GatewayLogRepository.successful().filter(pk=log.pk).exists()
        assert GatewayLogRepository.latest().pk == log.pk

    def test_repository_does_not_expose_mutation_for_immutable_logs(self):
        log = GatewayLogFactory()

        with pytest.raises((ValueError, ValidationError)):
            GatewayLogRepository.save(log, update_fields=["response_code"])

    def test_model_also_rejects_gateway_log_updates(self):
        log = GatewayLogFactory()
        log.response_code = "changed"

        # مدل ValidationError شلیک می‌کند
        with pytest.raises(ValidationError, match="immutable"):
            log.save(update_fields=["response_code"])

    def test_query_helpers_are_deterministically_ordered(self):
        attempt = PaymentAttemptFactory()
        first = GatewayLogFactory(attempt=attempt)
        second = GatewayLogFactory(attempt=attempt)

        assert list(GatewayLogRepository.for_attempt(attempt.pk)) == [first, second]
        assert GatewayLogRepository.latest_for_attempt(attempt.pk).pk == second.pk