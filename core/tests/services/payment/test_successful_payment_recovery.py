from __future__ import annotations

from unittest.mock import patch

import pytest

from order.events.order_event import OrderEventType
from order.models import (
    CouponReservation,
    CouponReservationStatus,
    OrderStatusType,
)
from order.services.coupon import CouponService
from payment.enums import (
    PaymentAttemptStatus,
    PaymentGateway,
    PaymentStatusType,
)
from payment.models import PaymentResolution
from payment.providers.base import GatewayVerificationResult
from payment.services.verify import (
    synchronize_successful_payment,
    verify_payment,
)
from tests.factories.order import OrderFactory
from tests.factories.payment import PaymentAttemptFactory, PaymentFactory
from tests.factories.shop import CouponFactory


pytestmark = pytest.mark.django_db(transaction=True)


def _successful_gateway_result(
    payment,
    *,
    reference: str,
) -> GatewayVerificationResult:
    return GatewayVerificationResult(
        success=True,
        gateway=PaymentGateway.ZARINPAL,
        gateway_reference=reference,
        gateway_transaction_id=f"TX-{reference}",
        response_code="100",
        message="verified",
        amount=payment.amount,
        currency=payment.currency,
    )


def test_successful_payment_is_recoverable_after_order_finalization_failure():
    """
    A process failure after Payment SUCCESS must not lose the ability
    to finalize the Order later.

    Phase C commits:
        Payment -> SUCCESS
        PaymentAttempt -> SUCCESS

    Order finalization then fails independently.

    A later synchronization must:
        consume the Payment exactly once;
        transition the Order to PAID exactly once;
        consume the coupon reservation exactly once;
        preserve the successful gateway evidence.
    """
    coupon = CouponFactory(max_limit_usage=1)

    order = OrderFactory(
        coupon=coupon,
        coupon_code=coupon.code,
        coupon_discount_percent=coupon.discount_percent,
    )
    CouponService.reserve_for_order(order)

    payment = PaymentFactory(order=order)
    attempt = PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        status=PaymentAttemptStatus.PENDING,
        authority_id="AUTH-RECOVERY-AFTER-FINALIZATION-FAILURE",
    )

    reference = "REF-RECOVERY-AFTER-FINALIZATION-FAILURE"

    with (
        patch(
            "payment.services.verify.GatewayService.verify",
            return_value=_successful_gateway_result(
                payment,
                reference=reference,
            ),
        ),
        patch(
            "payment.services.verify.confirm_order_payment",
            side_effect=RuntimeError(
                "Simulated process interruption before Order finalization."
            ),
        ),
    ):
        with pytest.raises(
            RuntimeError,
            match="Simulated process interruption",
        ):
            verify_payment(
                payment_id=payment.pk,
                attempt_id=attempt.pk,
                ref_id=reference,
            )

    # Gateway evidence must have committed before the independent
    # Order-finalization transaction failed.
    payment.refresh_from_db()
    attempt.refresh_from_db()
    order.refresh_from_db()
    coupon.refresh_from_db()

    assert payment.status == PaymentStatusType.SUCCESS
    assert payment.is_consumed is False

    assert attempt.status == PaymentAttemptStatus.SUCCESS
    assert attempt.authority_id == "AUTH-RECOVERY-AFTER-FINALIZATION-FAILURE"
    assert attempt.gateway_reference == reference
    assert attempt.gateway_transaction_id == f"TX-{reference}"

    assert order.status == OrderStatusType.pending
    assert not order.events.filter(type=OrderEventType.PAID).exists()

    reservation = CouponReservation.objects.get(order=order)
    assert reservation.status == CouponReservationStatus.RESERVED
    assert coupon.reserved_count == 1
    assert coupon.used_count == 0

    # An unexpected finalization failure must not be misclassified
    # as a terminal Order conflict.
    assert not PaymentResolution.objects.filter(payment=payment).exists()

    # Recovery uses the already-persisted SUCCESS evidence.
    # No second gateway verification is required.
    with patch(
        "payment.services.verify.GatewayService.verify",
    ) as gateway_verify:
        recovered_payment = synchronize_successful_payment(
            payment_id=payment.pk,
        )

    gateway_verify.assert_not_called()

    payment.refresh_from_db()
    attempt.refresh_from_db()
    order.refresh_from_db()
    coupon.refresh_from_db()
    reservation.refresh_from_db()

    assert recovered_payment.pk == payment.pk
    assert payment.status == PaymentStatusType.SUCCESS
    assert payment.is_consumed is True

    assert attempt.status == PaymentAttemptStatus.SUCCESS
    assert attempt.gateway_reference == reference
    assert attempt.gateway_transaction_id == f"TX-{reference}"

    assert order.status == OrderStatusType.paid
    assert order.paid_date is not None
    assert order.events.filter(type=OrderEventType.PAID).count() == 1

    assert reservation.status == CouponReservationStatus.CONSUMED
    assert coupon.reserved_count == 0
    assert coupon.used_count == 1

    # Repeated recovery must be idempotent.
    second_result = synchronize_successful_payment(
        payment_id=payment.pk,
    )

    payment.refresh_from_db()
    order.refresh_from_db()
    coupon.refresh_from_db()
    reservation.refresh_from_db()

    assert second_result.pk == payment.pk
    assert payment.is_consumed is True
    assert order.status == OrderStatusType.paid
    assert order.events.filter(type=OrderEventType.PAID).count() == 1

    assert reservation.status == CouponReservationStatus.CONSUMED
    assert coupon.reserved_count == 0
    assert coupon.used_count == 1