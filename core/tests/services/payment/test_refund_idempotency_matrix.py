from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from decimal import Decimal
from threading import Barrier, Event
from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, close_old_connections
from django.utils import timezone

from events.models.outbox import OutboxEvent
from order.events.order_event import OrderEventType
from order.models import OrderStatusType
from payment.enums import PaymentGateway, PaymentStatusType, RefundStatus
from payment.exceptions import PaymentInvariantViolation, PaymentRefundAmountInvalidError
from payment.models import Refund
from payment.providers.base import GatewayRefundInquiryResult, GatewayRefundResult
from payment.services.refund import RefundService
from payment.services.refund_recovery import RefundRecoveryWorker
from tests.concurrency.base import ConcurrentRunner
from tests.factories.accounts import UserFactory
from tests.factories.payment import PaymentAttemptFactory, PaymentFactory, RefundFactory

pytestmark = pytest.mark.django_db


def _payment(*, amount=Decimal("1000000")):
    payment = PaymentFactory(
        order__status=OrderStatusType.paid,
        order__paid_date=timezone.now(),
        order__total_price=amount,
        order__subtotal_price=amount,
        order__payable_price=amount,
        amount=amount,
        status=PaymentStatusType.SUCCESS,
        is_consumed=True,
        is_refunded=False,
    )
    PaymentAttemptFactory(payment=payment, attempt_number=1, success=True)
    return payment


def _success(reference):
    return GatewayRefundResult(
        success=True,
        gateway=PaymentGateway.ZARINPAL,
        gateway_reference=reference,
        gateway_transaction_id=f"TX-{reference}",
        response_code="100",
        message="Refund successful",
    )


def test_c4_partial_refund_key_cannot_be_reused_by_full_refund_entrypoint(admin_user):
    payment = _payment()
    with patch(
        "payment.services.refund.GatewayService.refund",
        side_effect=lambda **kwargs: _success(f"REF-{kwargs['refund'].pk}"),
    ) as gateway:
        partial = RefundService.refund(
            payment_id=payment.pk,
            amount=Decimal("300000"),
            idempotency_key="matrix-c4-partial-to-full",
            reason="customer_request",
            actor=admin_user,
        )
        RefundService.refund(
            payment_id=payment.pk,
            amount=Decimal("700000"),
            idempotency_key="matrix-c4-completing-refund",
            reason="customer_request",
            actor=admin_user,
        )

        with pytest.raises(PaymentInvariantViolation, match="different operation type"):
            RefundService.refund_order(
                order_id=payment.order_id,
                payment_id=payment.pk,
                actor=admin_user,
                idempotency_key="matrix-c4-partial-to-full",
            )

    assert Refund.objects.filter(payment=payment).count() == 2
    assert partial.amount == Decimal("300000")
    assert gateway.call_count == 2


def test_c4_full_refund_key_cannot_be_reused_by_amount_entrypoint(admin_user):
    payment = _payment()
    with patch(
        "payment.services.refund.GatewayService.refund",
        return_value=_success("REF-C4-FULL"),
    ) as gateway:
        full = RefundService.refund_order(
            order_id=payment.order_id,
            payment_id=payment.pk,
            actor=admin_user,
            idempotency_key="matrix-c4-full-to-amount",
        )

        with pytest.raises(PaymentInvariantViolation, match="different operation type"):
            RefundService.refund(
                payment_id=payment.pk,
                amount=full.amount,
                idempotency_key="matrix-c4-full-to-amount",
                reason="customer_request",
                actor=admin_user,
            )

    assert Refund.objects.filter(payment=payment).count() == 1
    gateway.assert_called_once()


def test_c2_same_key_different_amount_does_not_mutate_original_refund(admin_user):
    payment = _payment()
    with patch(
        "payment.services.refund.GatewayService.refund",
        return_value=_success("REF-C2"),
    ) as gateway:
        original = RefundService.refund(
            payment_id=payment.pk,
            amount=Decimal("300000"),
            idempotency_key="matrix-c2-key",
            reason="customer_request",
            actor=admin_user,
        )
        before = (original.amount, original.status, original.finished_at)
        payment.refresh_from_db()
        order_status_before = payment.order.status
        refunded_before = payment.is_refunded
        with pytest.raises(PaymentRefundAmountInvalidError):
            RefundService.refund(
                payment_id=payment.pk,
                amount=Decimal("200000"),
                idempotency_key="matrix-c2-key",
                reason="customer_request",
                actor=admin_user,
            )

    original.refresh_from_db()
    assert (original.amount, original.status, original.finished_at) == before
    assert Refund.objects.filter(idempotency_key="matrix-c2-key").count() == 1
    payment.refresh_from_db()
    payment.order.refresh_from_db()
    assert payment.is_refunded is refunded_before
    assert payment.order.status == order_status_before
    gateway.assert_called_once()


def test_c3_same_key_cannot_be_reused_for_another_payment(admin_user):
    payment_a = _payment()
    payment_b = _payment()
    with patch(
        "payment.services.refund.GatewayService.refund",
        return_value=_success("REF-C3"),
    ) as gateway:
        original = RefundService.refund(
            payment_id=payment_a.pk,
            amount=Decimal("300000"),
            idempotency_key="matrix-c3-cross-payment",
            reason="customer_request",
            actor=admin_user,
        )
        with pytest.raises(PaymentInvariantViolation, match="another Payment"):
            RefundService.refund(
                payment_id=payment_b.pk,
                amount=Decimal("300000"),
                idempotency_key="matrix-c3-cross-payment",
                reason="customer_request",
                actor=admin_user,
            )

    assert Refund.objects.filter(idempotency_key="matrix-c3-cross-payment").count() == 1
    assert Refund.objects.get(pk=original.pk).payment_id == payment_a.pk
    assert Refund.objects.filter(payment=payment_b).count() == 0
    payment_a.refresh_from_db()
    payment_b.refresh_from_db()
    assert payment_a.is_refunded is False
    assert payment_b.is_refunded is False
    assert payment_a.order.status == OrderStatusType.paid
    assert payment_b.order.status == OrderStatusType.paid
    gateway.assert_called_once()


def test_c1_repeated_full_refund_order_request_creates_one_financial_operation(admin_user):
    payment = _payment()
    with patch(
        "payment.services.refund.GatewayService.refund",
        return_value=_success("REF-C1"),
    ) as gateway:
        first = RefundService.refund_order(
            order_id=payment.order_id,
            payment_id=payment.pk,
            actor=admin_user,
            idempotency_key="matrix-c1-full",
        )
        second = RefundService.refund_order(
            order_id=payment.order_id,
            payment_id=payment.pk,
            actor=admin_user,
            idempotency_key="matrix-c1-full",
        )

    payment.refresh_from_db()
    payment.order.refresh_from_db()
    assert first.pk == second.pk
    assert Refund.objects.filter(payment=payment).count() == 1
    assert payment.is_refunded is True
    assert payment.order.status == OrderStatusType.refunded
    assert payment.order.events.filter(type=OrderEventType.REFUNDED).count() == 1
    assert OutboxEvent.objects.filter(topic="order.refunded").count() == 1
    gateway.assert_called_once()


def test_idempotency_shortcut_still_requires_staff_authorization(admin_user):
    payment = _payment()
    with patch(
        "payment.services.refund.GatewayService.refund",
        return_value=_success("REF-AUTH"),
    ) as gateway:
        RefundService.refund(
            payment_id=payment.pk,
            amount=Decimal("300000"),
            idempotency_key="matrix-auth",
            reason="customer_request",
            actor=admin_user,
        )
        with pytest.raises(PermissionDenied):
            RefundService.refund(
                payment_id=payment.pk,
                amount=Decimal("300000"),
                idempotency_key="matrix-auth",
                reason="customer_request",
                actor=UserFactory(),
            )

    gateway.assert_called_once()


def test_duplicate_inquiry_success_does_not_repeat_financial_finalization(admin_user):
    payment = _payment()
    pending = RefundFactory(
        payment=payment,
        amount=Decimal("1000000"),
        idempotency_key="matrix-c9-pending",
        status=RefundStatus.PENDING,
    )
    inquiry = GatewayRefundInquiryResult(
        success=True,
        status=RefundStatus.SUCCESS,
        gateway=PaymentGateway.ZARINPAL,
        gateway_reference="REF-C9",
        gateway_transaction_id="TX-C9",
        response_code="100",
        amount=pending.amount,
        currency=payment.currency,
    )
    with patch(
        "payment.services.refund.GatewayService.inquire_refund",
        return_value=inquiry,
    ) as inquiry_gateway, patch(
        "payment.services.refund.GatewayService.refund",
    ) as refund_gateway:
        first = RefundService.reconcile_pending_refund(refund_id=pending.pk)
        second = RefundService.reconcile_pending_refund(refund_id=pending.pk)

    payment.refresh_from_db()
    payment.order.refresh_from_db()
    assert first.pk == second.pk == pending.pk
    assert second.status == RefundStatus.SUCCESS
    assert payment.is_refunded is True
    assert payment.order.events.filter(type=OrderEventType.REFUNDED).count() == 1
    assert OutboxEvent.objects.filter(topic="order.refunded").count() == 1
    inquiry_gateway.call_count == 1  # terminal Refund bypasses a second inquiry
    refund_gateway.assert_not_called()


def test_c7_interrupted_local_finalization_recovers_without_refund_reexecution(admin_user):
    payment = _payment()
    gateway_result = _success("REF-C7")

    with patch(
        "payment.services.refund.GatewayService.refund",
        return_value=gateway_result,
    ) as refund_gateway, patch.object(
        RefundService,
        "_sync_payment_refund_state",
        side_effect=DatabaseError("simulated local persistence failure"),
    ):
        with pytest.raises(DatabaseError):
            RefundService.refund(
                payment_id=payment.pk,
                amount=payment.amount,
                idempotency_key="matrix-c7-interrupted",
                reason="customer_request",
                actor=admin_user,
            )

    pending = Refund.objects.get(idempotency_key="matrix-c7-interrupted")
    assert pending.status == RefundStatus.PENDING

    with patch("payment.services.refund.GatewayService.refund") as retry_gateway:
        retry = RefundService.refund(
            payment_id=payment.pk,
            amount=payment.amount,
            idempotency_key="matrix-c7-interrupted",
            reason="customer_request",
            actor=admin_user,
        )

    assert retry.pk == pending.pk
    retry_gateway.assert_not_called()
    refund_gateway.assert_called_once()

    inquiry = GatewayRefundInquiryResult(
        success=True,
        status=RefundStatus.SUCCESS,
        gateway=PaymentGateway.ZARINPAL,
        gateway_reference="REF-C7",
        gateway_transaction_id="TX-REF-C7",
        response_code="100",
        amount=pending.amount,
        currency=payment.currency,
    )
    with patch(
        "payment.services.refund.GatewayService.inquire_refund",
        return_value=inquiry,
    ) as inquiry_gateway, patch(
        "payment.services.refund.GatewayService.refund",
    ) as second_refund_gateway:
        recovered = RefundService.reconcile_pending_refund(refund_id=pending.pk)

    payment.refresh_from_db()
    payment.order.refresh_from_db()
    recovered.refresh_from_db()
    assert recovered.status == RefundStatus.SUCCESS
    assert payment.is_refunded is True
    assert payment.order.status == OrderStatusType.refunded
    assert payment.order.events.filter(type=OrderEventType.REFUNDED).count() == 1
    assert OutboxEvent.objects.filter(topic="order.refunded").count() == 1
    inquiry_gateway.assert_called_once()
    second_refund_gateway.assert_not_called()


def test_c8_repeated_success_finalization_has_no_duplicate_effects(admin_user):
    payment = _payment()
    with patch(
        "payment.services.refund.GatewayService.refund",
        return_value=_success("REF-C8"),
    ) as gateway:
        refund = RefundService.refund(
            payment_id=payment.pk,
            amount=payment.amount,
            idempotency_key="matrix-c8-finalize-twice",
            reason="customer_request",
            actor=admin_user,
        )

    payment.refresh_from_db()
    version_before = getattr(payment, "version", None)
    event_count_before = payment.order.events.filter(type=OrderEventType.REFUNDED).count()
    outbox_count_before = OutboxEvent.objects.filter(topic="order.refunded").count()

    duplicate = RefundService._finalize_success(
        payment_id=payment.pk,
        refund_id=refund.pk,
        gateway_reference="REF-C8",
        gateway_transaction_id="TX-REF-C8",
        response_code="100",
        gateway_message="Duplicate authoritative success",
        latency_ms=1,
    )

    payment.refresh_from_db()
    assert duplicate.pk == refund.pk
    assert duplicate.status == RefundStatus.SUCCESS
    assert payment.is_refunded is True
    if version_before is not None:
        assert payment.version == version_before
    assert payment.order.events.filter(type=OrderEventType.REFUNDED).count() == event_count_before
    assert OutboxEvent.objects.filter(topic="order.refunded").count() == outbox_count_before
    gateway.assert_called_once()


@pytest.mark.django_db(transaction=True)
def test_c10_concurrent_recovery_workers_finalize_one_refund_once():
    payment = _payment()
    pending = RefundFactory(
        payment=payment,
        amount=payment.amount,
        idempotency_key="matrix-c10-concurrent-recovery",
        status=RefundStatus.PENDING,
    )
    Refund.objects.filter(pk=pending.pk).update(
        requested_at=timezone.now() - timedelta(hours=2),
    )
    inquiry = GatewayRefundInquiryResult(
        success=True,
        status=RefundStatus.SUCCESS,
        gateway=PaymentGateway.ZARINPAL,
        gateway_reference="REF-C10",
        gateway_transaction_id="TX-C10",
        response_code="100",
        amount=pending.amount,
        currency=payment.currency,
    )
    start = Barrier(2)
    inquiry_started = Event()
    release_inquiry = Event()

    def inquire_refund(**kwargs):
        inquiry_started.set()
        assert release_inquiry.wait(timeout=15)
        return inquiry

    def worker():
        close_old_connections()
        try:
            start.wait(timeout=10)
            return RefundRecoveryWorker.run_batch(
                batch_size=10,
                older_than=timedelta(minutes=1),
                now=timezone.now() + timedelta(hours=2),
            )
        finally:
            close_old_connections()

    with patch(
        "payment.services.refund.GatewayService.inquire_refund",
        side_effect=inquire_refund,
    ) as inquiry_gateway, patch(
        "payment.services.refund.GatewayService.refund",
    ) as refund_gateway:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(worker) for _ in range(2)]
            assert inquiry_started.wait(timeout=10)
            completed = next(as_completed(futures, timeout=10))
            completed.result(timeout=10)
            release_inquiry.set()
            reports = [future.result(timeout=15) for future in futures]

    pending.refresh_from_db()
    payment.refresh_from_db()
    payment.order.refresh_from_db()
    assert pending.status == RefundStatus.SUCCESS
    assert sum(report.succeeded for report in reports) == 1
    assert inquiry_gateway.call_count == 1
    refund_gateway.assert_not_called()
    assert payment.is_refunded is True
    assert payment.order.events.filter(type=OrderEventType.REFUNDED).count() == 1
    assert OutboxEvent.objects.filter(topic="order.refunded").count() == 1


@pytest.mark.django_db(transaction=True)
def test_c5_concurrent_duplicate_full_refunds_persist_one_event_and_outbox(admin_user):
    payment = _payment()
    results = []

    def submit():
        refund = RefundService.refund_order(
            order_id=payment.order_id,
            payment_id=payment.pk,
            actor=admin_user,
            idempotency_key="matrix-c5-concurrent-full",
        )
        results.append(refund.pk)

    with patch(
        "payment.services.refund.GatewayService.refund",
        side_effect=lambda **kwargs: _success(f"REF-C5-{kwargs['refund'].pk}"),
    ) as gateway:
        ConcurrentRunner().run(submit, submit)

    payment.refresh_from_db()
    payment.order.refresh_from_db()
    assert len(results) == 2
    assert results[0] == results[1]
    assert Refund.objects.filter(payment=payment).count() == 1
    assert Refund.objects.get(payment=payment).amount == payment.amount
    assert payment.is_refunded is True
    assert payment.order.status == OrderStatusType.refunded
    assert payment.order.events.filter(type=OrderEventType.REFUNDED).count() == 1
    assert OutboxEvent.objects.filter(topic="order.refunded").count() == 1
    gateway.assert_called_once()