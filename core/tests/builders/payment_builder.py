# core/tests/builders/payment_builder.py
"""
Payment domain scenario builders.

These builders compose the existing payment factories into explicit,
meaningful financial test scenarios.

They do not implement production payment business rules.
They only validate the consistency of the requested test scenario
before delegating object creation to Factory Boy.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
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


class _PaymentScenarioState(StrEnum):
    """
    Internal semantic payment state requested by the scenario builder.

    This state is intentionally independent from Factory Boy trait names.

    The builder keeps requested state separate from effective state so
    that scenario composition remains explicit and conflicts cannot be
    silently overwritten.
    """

    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    CONSUMED = "consumed"
    REFUNDED = "refunded"


class _RefundScenarioState(StrEnum):
    """
    Internal semantic refund state.

    PENDING is explicit here even though RefundFactory represents it
    through its default state.
    """

    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass(frozen=True)
class PaymentScenario:
    """
    Result of a payment-domain scenario.

    Collections are tuples so the scenario container cannot be
    accidentally mutated after construction.
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

    Composition:

        User
          ↓
        Order
          ↓
        Payment
         ↙ ↘
    Attempt Refund
          ↘
        GatewayLog

    All persistence is delegated to existing factories.

    This builder does not implement production payment business rules.
    Its validation only protects test scenarios from being internally
    inconsistent.
    """

    __slots__ = (
        "_user",
        "_order",
        "_payment_states",
        "_attempt_states",
        "_refund_states",
        "_payment_log_requested",
        "_refund_log_requested",
    )

    def __init__(self) -> None:
        super().__init__()

        self._user: Optional[User] = None
        self._order: Optional[OrderModel] = None

        self._payment_states: list[_PaymentScenarioState] = []
        self._attempt_states: list[str] = []
        self._refund_states: list[_RefundScenarioState] = []

        self._payment_log_requested = False
        self._refund_log_requested = False

    # ================================
    # Context
    # ================================

    def with_user(self, user: User) -> PaymentScenarioBuilder:
        """
        Reuse an externally-created user.
        """
        self._user = user
        return self

    def with_order(
        self,
        order: OrderModel,
    ) -> PaymentScenarioBuilder:
        """
        Reuse an externally-created order.

        If no user has explicitly been supplied, the order owner becomes
        the scenario user.
        """
        self._order = order

        if self._user is None:
            self._user = order.user

        return self

    # ================================
    # Payment scenarios
    # ================================

    def _request_payment_state(
        self,
        state: _PaymentScenarioState,
    ) -> PaymentScenarioBuilder:
        self._payment_states.append(state)
        return self

    def pending_payment(self) -> PaymentScenarioBuilder:
        return self._request_payment_state(
            _PaymentScenarioState.PENDING,
        )

    def successful_payment(self) -> PaymentScenarioBuilder:
        return self._request_payment_state(
            _PaymentScenarioState.SUCCESS,
        )

    def failed_payment(self) -> PaymentScenarioBuilder:
        return self._request_payment_state(
            _PaymentScenarioState.FAILED,
        )

    def consumed_payment(self) -> PaymentScenarioBuilder:
        return self._request_payment_state(
            _PaymentScenarioState.CONSUMED,
        )

    def refunded_payment(self) -> PaymentScenarioBuilder:
        return self._request_payment_state(
            _PaymentScenarioState.REFUNDED,
        )

    def _resolve_payment_state(self) -> _PaymentScenarioState:
        """
        Resolve the explicitly requested payment state.

        Multiple different payment states are always rejected.

        This prevents accidental silent overrides such as:

            successful_payment().failed_payment()
        """
        if not self._payment_states:
            return _PaymentScenarioState.PENDING

        unique_states = set(self._payment_states)

        if len(unique_states) > 1:
            names = ", ".join(
                state.value
                for state in self._payment_states
            )

            raise ValueError(
                "Conflicting payment states requested: "
                f"{names}."
            )

        return self._payment_states[0]

    def _effective_payment_state(self) -> _PaymentScenarioState:
        """
        Resolve the final semantic payment state after considering
        dependent scenario components.

        A Refund transaction requires a consumed successful Payment.

        Therefore:

            successful_payment()
            + refund

        semantically becomes:

            consumed_payment()
            + refund

        This is scenario composition, not production business logic.
        """
        requested_state = self._resolve_payment_state()

        if (
            self._refund_states
            and requested_state == _PaymentScenarioState.SUCCESS
        ):
            return _PaymentScenarioState.CONSUMED

        return requested_state

    # ================================
    # Attempts
    # ================================

    def successful_attempt(self) -> PaymentScenarioBuilder:
        """
        Create one successful payment attempt.
        """
        self._attempt_states.append("success")
        return self

    def failed_attempt(self) -> PaymentScenarioBuilder:
        """
        Create one failed payment attempt.
        """
        self._attempt_states.append("failed")
        return self

    def timeout_attempt(self) -> PaymentScenarioBuilder:
        """
        Create one timed-out payment attempt.
        """
        self._attempt_states.append("timeout")
        return self

    def cancelled_attempt(self) -> PaymentScenarioBuilder:
        """
        Create one cancelled payment attempt.
        """
        self._attempt_states.append("cancelled")
        return self

    # ================================
    # Refunds
    # ================================

    def pending_refund(self) -> PaymentScenarioBuilder:
        """
        Create one pending refund.
        """
        self._refund_states.append(
            _RefundScenarioState.PENDING,
        )
        return self

    def successful_refund(self) -> PaymentScenarioBuilder:
        """
        Create one successful refund.

        The effective payment state will automatically become CONSUMED
        when the explicitly requested payment state is SUCCESS.
        """
        self._refund_states.append(
            _RefundScenarioState.SUCCESS,
        )
        return self

    def failed_refund(self) -> PaymentScenarioBuilder:
        """
        Create one failed refund.

        The effective payment state will automatically become CONSUMED
        when the explicitly requested payment state is SUCCESS.
        """
        self._refund_states.append(
            _RefundScenarioState.FAILED,
        )
        return self

    # ================================
    # Gateway logs
    # ================================

    def payment_log(self) -> PaymentScenarioBuilder:
        """
        Request gateway request logs for payment attempts.
        """
        self._payment_log_requested = True
        return self

    def refund_log(self) -> PaymentScenarioBuilder:
        """
        Request gateway refund logs for refunds.
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
    # Build
    # ================================

    def build(self) -> PaymentScenario:
        """
        Build the complete payment scenario.
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
    # Resolution
    # ================================

    def _resolve_order(self) -> tuple[User, OrderModel]:
        """
        Resolve the order without replacing an explicitly supplied order.
        """
        if self._order is not None:
            user = self._user or self._order.user

            if user.pk != self._order.user_id:
                raise ValueError(
                    "The supplied user does not own the supplied order."
                )

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
    # Validation
    # ================================

    def _validate_configuration(self) -> None:
        """
        Validate the final effective scenario.

        IMPORTANT:

        Validation MUST use _effective_payment_state(), not
        _resolve_payment_state().

        Otherwise a successful payment with a refund is incorrectly
        rejected before the builder gets a chance to promote the
        effective state to CONSUMED.
        """

        requested_state = self._resolve_payment_state()
        effective_state = self._effective_payment_state()

        has_refunds = bool(self._refund_states)
        has_payment_log = self._payment_log_requested
        has_refund_log = self._refund_log_requested

        # ------------------------------------
        # Refund prerequisites
        # ------------------------------------

        if has_refunds and effective_state != _PaymentScenarioState.CONSUMED:
            raise ValueError(
                "Refund scenarios require a successful and consumed "
                "payment."
            )

        # ------------------------------------
        # Refund logs
        # ------------------------------------

        if has_refund_log and not has_refunds:
            raise ValueError(
                "refund_log() requires at least one refund scenario."
            )

        # ------------------------------------
        # Payment logs
        # ------------------------------------

        if has_payment_log and not self._attempt_states:
            raise ValueError(
                "payment_log() requires at least one payment attempt."
            )

        # ------------------------------------
        # Refunded aggregate vs refund transaction
        # ------------------------------------

        if (
            requested_state == _PaymentScenarioState.REFUNDED
            and has_refunds
        ):
            raise ValueError(
                "A refunded_payment() scenario must not also create "
                "Refund transactions. Use consumed_payment() when "
                "Refund objects themselves are under test."
            )

    # ================================
    # Payment
    # ================================

    def _build_payment(
        self,
        order: OrderModel,
    ) -> PaymentModel:
        """
        Build the Payment aggregate from the effective scenario state.
        """
        state = self._effective_payment_state()

        kwargs: dict[str, object] = {
            "order": order,
        }

        if state == _PaymentScenarioState.SUCCESS:
            kwargs["success"] = True

        elif state == _PaymentScenarioState.FAILED:
            kwargs["failed"] = True

        elif state == _PaymentScenarioState.CONSUMED:
            kwargs["consumed"] = True

        elif state == _PaymentScenarioState.REFUNDED:
            kwargs["refunded"] = True

        return PaymentFactory.create(**kwargs)

    # ================================
    # Attempts
    # ================================

    def _build_attempts(
        self,
        payment: PaymentModel,
    ) -> list[PaymentAttempt]:
        """
        Build attempts against the already-created payment.
        """
        attempts: list[PaymentAttempt] = []

        for trait in self._attempt_states:
            attempt = PaymentAttemptFactory.create(
                payment=payment,
                **{trait: True},
            )

            attempts.append(attempt)

        return attempts

    # ================================
    # Refunds
    # ================================

    def _build_refunds(
        self,
        payment: PaymentModel,
    ) -> list[Refund]:
        """
        Build refunds against the already-created payment.

        PENDING is represented by the RefundFactory default.

        SUCCESS and FAILED use their explicit Factory Boy traits.
        """
        refunds: list[Refund] = []

        for state in self._refund_states:
            kwargs: dict[str, object] = {
                "payment": payment,
            }

            if state == _RefundScenarioState.SUCCESS:
                kwargs["success"] = True

            elif state == _RefundScenarioState.FAILED:
                kwargs["failed"] = True

            elif state == _RefundScenarioState.PENDING:
                # PENDING is RefundFactory's default state.
                pass

            else:
                raise ValueError(
                    f"Unsupported refund scenario state: {state!r}"
                )

            refund = RefundFactory.create(**kwargs)
            refunds.append(refund)

        return refunds

    # ================================
    # Gateway logs
    # ================================

    def _build_logs(
        self,
        *,
        attempts: list[PaymentAttempt],
        refunds: list[Refund],
    ) -> list[GatewayLog]:
        """
        Build gateway logs only for explicitly requested objects.

        The builder never creates implicit attempts/refunds merely
        to satisfy a log request.
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