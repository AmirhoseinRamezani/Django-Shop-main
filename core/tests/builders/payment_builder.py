"""
Payment domain scenario builders.

These builders compose the existing payment factories into explicit,
meaningful financial test scenarios.

They do not implement payment business rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from accounts.models import User
from order.models import OrderModel
from payment.enums import (
    GatewayLogDirection,
    GatewayLogType,
    PaymentGateway,
)
from payment.models import (
    GatewayLog,
    PaymentAttempt,
    PaymentModel,
    Refund,
)

from tests.builders.base import BaseBuilder
from tests.builders.order_builder import OrderScenarioBuilder
from tests.factories.payment import (
    GatewayLogFactory,
    PaymentAttemptFactory,
    PaymentFactory,
    RefundFactory,
)


@dataclass(frozen=True)
class PaymentScenario:
    """
    Result of a payment-domain scenario.

    Collections are tuples so that the returned scenario cannot be
    accidentally mutated at the container level by a test.
    """

    user: User
    order: OrderModel
    payment: PaymentModel
    attempts: tuple[PaymentAttempt, ...] = ()
    refunds: tuple[Refund, ...] = ()
    logs: tuple[GatewayLog, ...] = ()


class PaymentScenarioBuilder(BaseBuilder[PaymentScenario]):
    """
    High-level builder for payment scenarios.

    The builder composes:

        User
        Order
        Payment
        PaymentAttempt
        Refund
        GatewayLog

    It does not implement payment state transitions or gateway logic.
    """

    __slots__ = (
        "_user",
        "_order",
        "_payment_state",
        "_payment_state_conflict",
        "_attempt_traits",
        "_refund_states",
        "_payment_log_requested",
        "_refund_log_requested",
    )

    def __init__(self) -> None:
        super().__init__()

        self._user: Optional[User] = None
        self._order: Optional[OrderModel] = None

        # None means "use the PaymentFactory default".
        self._payment_state: Optional[str] = None
        self._payment_state_conflict: Optional[tuple[str, str]] = None

        self._attempt_traits: list[str] = []
        self._refund_states: list[str] = []

        self._payment_log_requested = False
        self._refund_log_requested = False

    # ================================
    # CONTEXT
    # ================================

    def with_user(self, user: User) -> PaymentScenarioBuilder:
        """
        Use an externally-created user.

        The supplied user is reused and never replaced silently.
        """
        self._user = user
        return self

    def with_order(self, order: OrderModel) -> PaymentScenarioBuilder:
        """
        Use an externally-created order.

        If no user was supplied explicitly, the order's user becomes
        the scenario user.
        """
        self._order = order

        if self._user is None:
            self._user = order.user

        return self

    # ================================
    # PAYMENT STATES
    # ================================

    def pending_payment(self) -> PaymentScenarioBuilder:
        """
        Configure a pending payment.

        This is also the PaymentFactory default state.
        """
        self._set_payment_state("pending")
        return self

    def successful_payment(self) -> PaymentScenarioBuilder:
        """Configure a successful payment."""
        self._set_payment_state("success")
        return self

    def failed_payment(self) -> PaymentScenarioBuilder:
        """Configure a failed payment."""
        self._set_payment_state("failed")
        return self

    def consumed_payment(self) -> PaymentScenarioBuilder:
        """
        Configure a successful, consumed payment.
        """
        self._set_payment_state("consumed")
        return self

    def refunded_payment(self) -> PaymentScenarioBuilder:
        """
        Configure a successful, consumed and refunded payment.
        """
        self._set_payment_state("refunded")
        return self

    def _set_payment_state(self, state: str) -> None:
        """
        Set the requested payment scenario.

        A builder must not silently replace one explicitly requested
        payment state with another.
        """
        if self._payment_state is None:
            self._payment_state = state
            return

        if self._payment_state == state:
            return

        self._payment_state_conflict = (
            self._payment_state,
            state,
        )

    # ================================
    # PAYMENT ATTEMPTS
    # ================================

    def successful_attempt(self) -> PaymentScenarioBuilder:
        """Add a successful payment attempt."""
        self._attempt_traits.append("success")
        return self

    def failed_attempt(self) -> PaymentScenarioBuilder:
        """Add a failed payment attempt."""
        self._attempt_traits.append("failed")
        return self

    def timeout_attempt(self) -> PaymentScenarioBuilder:
        """Add a timeout payment attempt."""
        self._attempt_traits.append("timeout")
        return self

    def cancelled_attempt(self) -> PaymentScenarioBuilder:
        """Add a cancelled payment attempt."""
        self._attempt_traits.append("cancelled")
        return self

    # ================================
    # REFUNDS
    # ================================

    def pending_refund(self) -> PaymentScenarioBuilder:
        """
        Add a pending refund.

        Pending is the default RefundFactory state, so no fake
        ``pending`` Factory trait is passed.
        """
        self._refund_states.append("pending")
        return self

    def successful_refund(self) -> PaymentScenarioBuilder:
        """Add a successful refund."""
        self._refund_states.append("success")
        return self

    def failed_refund(self) -> PaymentScenarioBuilder:
        """Add a failed refund."""
        self._refund_states.append("failed")
        return self

    # ================================
    # GATEWAY LOGS
    # ================================

    def payment_log(self) -> PaymentScenarioBuilder:
        """
        Request a gateway request log for every configured attempt.
        """
        self._payment_log_requested = True
        return self

    def refund_log(self) -> PaymentScenarioBuilder:
        """
        Request a gateway refund log for every configured refund.
        """
        self._refund_log_requested = True
        return self

    def with_gateway_logs(self) -> PaymentScenarioBuilder:
        """
        Request both payment-attempt and refund gateway logs.
        """
        self._payment_log_requested = True
        self._refund_log_requested = True
        return self

    # ================================
    # BUILD
    # ================================

    def build(self) -> PaymentScenario:
        """
        Construct the configured payment scenario.
        """
        self._mark_built()

        self._validate_configuration()

        user, order = self._resolve_order()

        payment = self._build_payment(order)

        attempts = self._build_attempts(payment)
        refunds = self._build_refunds(payment)

        logs = self._build_logs(
            attempts=attempts,
            refunds=refunds,
        )

        return PaymentScenario(
            user=user,
            order=order,
            payment=payment,
            attempts=tuple(attempts),
            refunds=tuple(refunds),
            logs=tuple(logs),
        )

    # ================================
    # ORDER RESOLUTION
    # ================================

    def _resolve_order(self) -> tuple[User, OrderModel]:
        """
        Resolve the order/user context.

        An externally supplied order is always reused.
        """
        if self._order is not None:
            user = self._user or self._order.user
            return user, self._order

        builder = OrderScenarioBuilder()

        if self._user is not None:
            builder.with_user(self._user)

        scenario = (
            builder
            .with_items(1)
            .build()
        )

        return scenario.user, scenario.order

    # ================================
    # VALIDATION
    # ================================

    def _validate_configuration(self) -> None:
        """
        Validate Builder configuration.

        This is configuration validation only. It does not implement
        production payment rules.
        """
        if self._payment_state_conflict is not None:
            first, second = self._payment_state_conflict

            raise ValueError(
                "A payment scenario cannot contain conflicting "
                f"payment states: {first!r} and {second!r}."
            )

        payment_state = self._payment_state

        if payment_state in {"consumed", "refunded"}:
            if payment_state not in {"consumed", "refunded"}:
                raise ValueError(
                    "Invalid payment state configuration."
                )

        if payment_state == "refunded":
            # A refunded payment is necessarily represented by the
            # PaymentFactory's refunded trait.
            pass

        if self._refund_states and payment_state not in {
            "success",
            "consumed",
            "refunded",
        }:
            raise ValueError(
                "Refund scenarios require a successful payment."
            )

        if self._refund_log_requested and not self._refund_states:
            raise ValueError(
                "refund_log() requires at least one refund scenario."
            )

        if self._payment_log_requested and not self._attempt_traits:
            raise ValueError(
                "payment_log() requires at least one payment attempt."
            )

    # ================================
    # PAYMENT
    # ================================

    def _build_payment(self, order: OrderModel) -> PaymentModel:
        """
        Build the Payment aggregate through PaymentFactory.
        """
        kwargs: dict[str, object] = {
            "order": order,
        }

        state = self._payment_state

        if state == "success":
            kwargs["success"] = True

        elif state == "failed":
            kwargs["failed"] = True

        elif state == "consumed":
            kwargs["consumed"] = True

        elif state == "refunded":
            kwargs["refunded"] = True

        # ``pending`` and ``None`` intentionally use Factory defaults.
        return PaymentFactory.create(**kwargs)

    # ================================
    # ATTEMPTS
    # ================================

    def _build_attempts(
        self,
        payment: PaymentModel,
    ) -> list[PaymentAttempt]:
        """
        Build all requested attempts through PaymentAttemptFactory.
        """
        attempts: list[PaymentAttempt] = []

        for trait in self._attempt_traits:
            attempt = PaymentAttemptFactory.create(
                payment=payment,
                **{trait: True},
            )
            attempts.append(attempt)

        return attempts

    # ================================
    # REFUNDS
    # ================================

    def _build_refunds(
        self,
        payment: PaymentModel,
    ) -> list[Refund]:
        """
        Build all requested refunds through RefundFactory.

        Important:
            ``pending`` is the RefundFactory default and is NOT a
            Factory Boy trait.
        """
        refunds: list[Refund] = []

        for state in self._refund_states:
            if state == "pending":
                refund = RefundFactory.create(
                    payment=payment,
                )

            elif state == "success":
                refund = RefundFactory.create(
                    payment=payment,
                    success=True,
                )

            elif state == "failed":
                refund = RefundFactory.create(
                    payment=payment,
                    failed=True,
                )

            else:
                raise ValueError(
                    f"Unsupported refund scenario: {state!r}"
                )

            refunds.append(refund)

        return refunds

    # ================================
    # GATEWAY LOGS
    # ================================

    def _build_logs(
        self,
        *,
        attempts: list[PaymentAttempt],
        refunds: list[Refund],
    ) -> list[GatewayLog]:
        """
        Build gateway logs with explicit attempt/refund ownership.
        """
        logs: list[GatewayLog] = []

        if self._payment_log_requested:
            for attempt in attempts:
                logs.append(
                    GatewayLogFactory.create(
                        attempt=attempt,
                        refund=None,
                        gateway=PaymentGateway.ZARINPAL,
                        log_type=GatewayLogType.REQUEST,
                        direction=GatewayLogDirection.OUTBOUND,
                    )
                )

        if self._refund_log_requested:
            for refund in refunds:
                logs.append(
                    GatewayLogFactory.create(
                        attempt=None,
                        refund=refund,
                        gateway=PaymentGateway.ZARINPAL,
                        log_type=GatewayLogType.REFUND,
                        direction=GatewayLogDirection.OUTBOUND,
                    )
                )

        return logs