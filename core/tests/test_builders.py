# tests/test_builders.py
"""
Tests for domain scenario builders.

These tests verify:
    - scenario composition
    - relationships
    - state consistency
    - optional components
    - builder lifecycle

They intentionally do not test Factory Boy internals.
"""

import pytest

from payment.enums import (
    PaymentAttemptStatus,
    PaymentStatusType,
    RefundStatus,
)

from tests.builders.accounts_builder import AccountScenarioBuilder
from tests.builders.order_builder import OrderScenarioBuilder
from tests.builders.payment_builder import PaymentScenarioBuilder


pytestmark = pytest.mark.django_db

class TestAccountScenarioBuilder:
    def test_default_account(self):
        scenario = AccountScenarioBuilder().build()

        assert scenario.user.pk is not None
        assert scenario.profile is not None
        assert scenario.profile.pk is not None

        assert scenario.sessions == ()
        assert scenario.tokens == ()

    def test_admin_account(self):
        scenario = (
            AccountScenarioBuilder()
            .as_admin()
            .build()
        )

        assert scenario.user.is_staff is True

    def test_refresh_token_requires_session(self):
        scenario = (
            AccountScenarioBuilder()
            .with_refresh_token()
            .build()
        )

        assert len(scenario.sessions) == 1
        assert len(scenario.tokens) == 1

        assert scenario.sessions[0].user_id == scenario.user.pk
        assert scenario.tokens[0].user_id == scenario.user.pk
        assert scenario.tokens[0].session_id == scenario.sessions[0].pk

    def test_existing_user_is_reused(self):
        from tests.factories.accounts import UserFactory

        user = UserFactory.create()

        scenario = (
            AccountScenarioBuilder()
            .with_user(user)
            .build()
        )

        assert scenario.user.pk == user.pk


class TestOrderScenarioBuilder:
    def test_default_order_is_minimal(self):
        scenario = OrderScenarioBuilder().build()

        assert scenario.order.pk is not None
        assert scenario.user.pk == scenario.order.user_id
        assert scenario.items == ()
        assert scenario.coupon is None

    def test_items_belong_to_order(self):
        scenario = (
            OrderScenarioBuilder()
            .with_items(2)
            .build()
        )

        assert len(scenario.items) == 2

        for item in scenario.items:
            assert item.order_id == scenario.order.pk

    def test_existing_user_is_reused(self):
        from tests.factories.accounts import UserFactory

        user = UserFactory.create()

        scenario = (
            OrderScenarioBuilder()
            .with_user(user)
            .build()
        )

        assert scenario.user.pk == user.pk
        assert scenario.order.user_id == user.pk

    def test_coupon_is_attached(self):
        scenario = (
            OrderScenarioBuilder()
            .with_coupon()
            .build()
        )

        assert scenario.coupon is not None
        assert scenario.order.coupon_id == scenario.coupon.pk


class TestPaymentScenarioBuilder:
    def test_default_payment_scenario(self):
        scenario = PaymentScenarioBuilder().build()

        assert scenario.user.pk is not None
        assert scenario.order.pk is not None
        assert scenario.payment.pk is not None

        assert scenario.payment.order_id == scenario.order.pk

        assert scenario.attempts == ()
        assert scenario.refunds == ()
        assert scenario.logs == ()

    def test_successful_payment(self):
        scenario = (
            PaymentScenarioBuilder()
            .successful_payment()
            .build()
        )

        assert scenario.payment.status == PaymentStatusType.SUCCESS
        assert scenario.payment.is_successful is True

    def test_failed_payment(self):
        scenario = (
            PaymentScenarioBuilder()
            .failed_payment()
            .build()
        )

        assert scenario.payment.status == PaymentStatusType.FAILED
        assert scenario.payment.is_failed is True

    def test_consumed_payment(self):
        scenario = (
            PaymentScenarioBuilder()
            .consumed_payment()
            .build()
        )

        assert scenario.payment.status == PaymentStatusType.SUCCESS
        assert scenario.payment.is_consumed is True
        assert scenario.payment.can_consume is False

    def test_refunded_payment(self):
        scenario = (
            PaymentScenarioBuilder()
            .refunded_payment()
            .build()
        )

        assert scenario.payment.status == PaymentStatusType.SUCCESS
        assert scenario.payment.is_consumed is True
        assert scenario.payment.is_refunded is True
        assert scenario.payment.is_fully_refunded is True

    def test_successful_attempt(self):
        scenario = (
            PaymentScenarioBuilder()
            .successful_payment()
            .successful_attempt()
            .build()
        )

        assert len(scenario.attempts) == 1

        attempt = scenario.attempts[0]

        assert attempt.payment_id == scenario.payment.pk
        assert attempt.status == PaymentAttemptStatus.SUCCESS
        assert attempt.finished_at is not None
        assert attempt.is_terminal is True

    def test_failed_attempt(self):
        scenario = (
            PaymentScenarioBuilder()
            .failed_payment()
            .failed_attempt()
            .build()
        )

        assert len(scenario.attempts) == 1

        attempt = scenario.attempts[0]

        assert attempt.payment_id == scenario.payment.pk
        assert attempt.status == PaymentAttemptStatus.FAILED
        assert attempt.finished_at is not None
        assert attempt.is_terminal is True

    def test_timeout_attempt(self):
        scenario = (
            PaymentScenarioBuilder()
            .successful_payment()
            .timeout_attempt()
            .build()
        )

        attempt = scenario.attempts[0]

        assert attempt.payment_id == scenario.payment.pk
        assert attempt.status == PaymentAttemptStatus.TIMEOUT
        assert attempt.finished_at is not None
        assert attempt.is_terminal is True

    def test_cancelled_attempt(self):
        scenario = (
            PaymentScenarioBuilder()
            .successful_payment()
            .cancelled_attempt()
            .build()
        )

        attempt = scenario.attempts[0]

        assert attempt.payment_id == scenario.payment.pk
        assert attempt.status == PaymentAttemptStatus.CANCELLED
        assert attempt.finished_at is not None
        assert attempt.is_terminal is True

    def test_successful_refund(self):
        scenario = (
            PaymentScenarioBuilder()
            .successful_payment()
            .successful_refund()
            .build()
        )

        assert scenario.payment.status == PaymentStatusType.SUCCESS
        assert scenario.payment.is_consumed is True

        assert len(scenario.refunds) == 1

        refund = scenario.refunds[0]

        assert refund.payment_id == scenario.payment.pk
        assert refund.status == RefundStatus.SUCCESS
        assert refund.finished_at is not None
        assert refund.is_terminal is True

    def test_pending_refund(self):
        scenario = (
            PaymentScenarioBuilder()
            .consumed_payment()
            .pending_refund()
            .build()
        )

        assert scenario.payment.is_consumed is True
        assert len(scenario.refunds) == 1
        assert scenario.refunds[0].is_pending is True

    def test_failed_refund(self):
        scenario = (
            PaymentScenarioBuilder()
            .consumed_payment()
            .failed_refund()
            .build()
        )

        assert scenario.payment.is_consumed is True
        assert len(scenario.refunds) == 1
        assert scenario.refunds[0].is_failed is True

    def test_payment_log(self):
        scenario = (
            PaymentScenarioBuilder()
            .successful_payment()
            .successful_attempt()
            .payment_log()
            .build()
        )

        assert len(scenario.logs) == 1

        log = scenario.logs[0]

        assert log.attempt_id == scenario.attempts[0].pk
        assert log.refund_id is None

    def test_refund_log(self):
        scenario = (
            PaymentScenarioBuilder()
            .successful_payment()
            .successful_refund()
            .refund_log()
            .build()
        )

        assert len(scenario.logs) == 1

        log = scenario.logs[0]

        assert log.refund_id == scenario.refunds[0].pk
        assert log.attempt_id is None
        
    def test_successful_payment_with_refund_is_effectively_consumed(self):
        scenario = (
            PaymentScenarioBuilder()
            .successful_payment()
            .successful_refund()
            .build()
        )

        assert scenario.payment.status == PaymentStatusType.SUCCESS
        assert scenario.payment.is_consumed is True
        assert scenario.payment.can_refund is True

        assert len(scenario.refunds) == 1
        assert scenario.refunds[0].payment_id == scenario.payment.pk

    def test_complete_payment_scenario(self):
        scenario = (
            PaymentScenarioBuilder()
            .successful_payment()
            .successful_attempt()
            .successful_refund()
            .with_gateway_logs()
            .build()
        )

        assert scenario.payment.status == PaymentStatusType.SUCCESS
        assert scenario.payment.is_consumed is True

        assert len(scenario.attempts) == 1
        assert scenario.attempts[0].status == PaymentAttemptStatus.SUCCESS

        assert len(scenario.refunds) == 1
        assert scenario.refunds[0].status == RefundStatus.SUCCESS

        assert len(scenario.logs) == 2

        payment_log = next(
            log
            for log in scenario.logs
            if log.attempt_id is not None
        )

        refund_log = next(
            log
            for log in scenario.logs
            if log.refund_id is not None
        )

        assert payment_log.attempt_id == scenario.attempts[0].pk
        assert payment_log.refund_id is None

        assert refund_log.refund_id == scenario.refunds[0].pk
        assert refund_log.attempt_id is None

    def test_existing_order_is_reused(self):
        order_scenario = (
            OrderScenarioBuilder()
            .with_items(1)
            .build()
        )

        scenario = (
            PaymentScenarioBuilder()
            .with_order(order_scenario.order)
            .successful_payment()
            .build()
        )

        assert scenario.order.pk == order_scenario.order.pk
        assert scenario.payment.order_id == order_scenario.order.pk

    def test_existing_user_is_reused(self):
        from tests.factories.accounts import UserFactory

        user = UserFactory.create()

        scenario = (
            PaymentScenarioBuilder()
            .with_user(user)
            .successful_payment()
            .build()
        )

        assert scenario.user.pk == user.pk
        assert scenario.order.user_id == user.pk
        assert scenario.payment.order_id == scenario.order.pk

    def test_refund_requires_successful_payment(self):
        builder = (
            PaymentScenarioBuilder()
            .pending_payment()
            .successful_refund()
        )

        with pytest.raises(ValueError):
            builder.build()

    def test_refund_requires_consumable_payment(self):
        builder = (
            PaymentScenarioBuilder()
            .failed_payment()
            .successful_refund()
        )

        with pytest.raises(ValueError):
            builder.build()

    def test_refund_log_requires_refund(self):
        builder = (
            PaymentScenarioBuilder()
            .successful_payment()
            .refund_log()
        )

        with pytest.raises(ValueError):
            builder.build()

    def test_payment_log_requires_attempt(self):
        builder = (
            PaymentScenarioBuilder()
            .successful_payment()
            .payment_log()
        )

        with pytest.raises(ValueError):
            builder.build()

    def test_conflicting_payment_states_are_rejected(self):
        builder = (
            PaymentScenarioBuilder()
            .successful_payment()
            .failed_payment()
        )
        with pytest.raises(ValueError):
            builder.build()

    def test_builder_is_single_use(self):
        builder = (
            PaymentScenarioBuilder()
            .successful_payment()
        )

        scenario = builder.build()

        assert scenario.payment.pk is not None

        with pytest.raises(RuntimeError):
            builder.build()