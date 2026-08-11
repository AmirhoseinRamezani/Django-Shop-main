# core/payment/models/payment.py

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F
from django.utils.translation import gettext_lazy as _

from order.models import OrderModel
from payment.enums import (
    Currency,
    PaymentGateway,
    PaymentStatusType,
)
from payment.managers import PaymentManager


class PaymentModel(models.Model):
    """
    Payment Aggregate Root.

    ================================
    ARCHITECTURAL RESPONSIBILITY
    ================================

    Payment owns:

        - financial amount
        - currency
        - selected gateway
        - payment lifecycle
        - consumption state
        - refund eligibility
        - aggregate invariants
        - domain state transitions

    Payment does NOT own:

        - gateway communication
        - HTTP
        - PaymentAttempt queries
        - repository queries
        - transaction.atomic()
        - Celery dispatch
        - Order mutation
        - external events
        - gateway verification

    ================================
    STATE MACHINE
    ================================

        PENDING
           |
           +------> SUCCESS
           |
           +------> FAILED

        SUCCESS -> SUCCESS   idempotent
        FAILED  -> FAILED    idempotent

    Forbidden:

        SUCCESS -> FAILED
        SUCCESS -> PENDING
        FAILED  -> SUCCESS
        FAILED  -> PENDING

    ================================
    CONCURRENCY
    ================================

    Payment exposes a version field.

    IMPORTANT:

    The existence of `version` does NOT by itself provide
    optimistic locking.

    The actual optimistic concurrency contract belongs to the
    repository.

    The repository must perform:

        UPDATE ... WHERE id = ? AND version = expected_version

    and increment version atomically.

    ================================
    FINANCIAL IMMUTABILITY
    ================================

    Amount and currency represent the financial snapshot of this
    Payment.

    They must not be changed after the Payment has been created.

    Application Services are responsible for preventing such
    mutation.

    The model additionally exposes a guard method so Services can
    explicitly validate the financial snapshot.
    """

    # ================================
    # Identity
    # ================================

    order = models.ForeignKey(
        OrderModel,
        on_delete=models.PROTECT,
        related_name="payments",
    )

    # ================================
    # Financial State
    # ================================

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        help_text=_(
            "Immutable financial amount of this payment."
        ),
    )

    currency = models.CharField(
        max_length=8,
        choices=Currency.choices,
        default=Currency.IRR,
        help_text=_(
            "Immutable currency of this payment."
        ),
    )

    gateway = models.CharField(
        max_length=32,
        choices=PaymentGateway.choices,
        db_index=True,
        help_text=_(
            "Payment gateway selected for this payment."
        ),
    )

    status = models.PositiveSmallIntegerField(
        choices=PaymentStatusType.choices,
        default=PaymentStatusType.PENDING,
        db_index=True,
    )

    # ================================
    # Optimistic Concurrency
    # ================================

    version = models.PositiveIntegerField(
        default=1,
        help_text=_(
            "Optimistic concurrency version. "
            "The repository owns atomic version checking."
        ),
    )

    # ================================
    # Business Flags
    # ================================

    is_consumed = models.BooleanField(
        default=False,
    )

    is_refunded = models.BooleanField(
        default=False,
    )

    # ================================
    # Audit
    # ================================

    created_date = models.DateTimeField(
        auto_now_add=True,
    )

    updated_date = models.DateTimeField(
        auto_now=True,
    )

    objects = PaymentManager()

    # ================================
    # Meta
    # ================================

    class Meta:
        verbose_name = _("Payment")
        verbose_name_plural = _("Payments")

        ordering = (
            "-created_date",
            "-id",
        )

        indexes = [
            models.Index(
                fields=[
                    "status",
                ],
                name="payment_status_idx",
            ),
            models.Index(
                fields=[
                    "gateway",
                    "status",
                ],
                name="payment_gateway_status_idx",
            ),
            models.Index(
                fields=[
                    "order",
                    "status",
                ],
                name="payment_order_status_idx",
            ),
            models.Index(
                fields=[
                    "created_date",
                ],
                name="payment_created_idx",
            ),
        ]

        constraints = [
            models.CheckConstraint(
                condition=(
                    F("amount") > Decimal("0")
                ),
                name="payment_amount_positive",
            ),
            models.CheckConstraint(
                condition=(
                    F("version") >= 1
                ),
                name="payment_version_positive",
            ),
        ]

    # ================================
    # State API
    # ================================

    @property
    def state(self) -> PaymentStatusType:
        """
        Return the strongly typed current state.
        """

        return PaymentStatusType(
            self.status
        )

    def is_state(
        self,
        state: PaymentStatusType,
    ) -> bool:
        return self.state == state

    def in_state(
        self,
        *states: PaymentStatusType,
    ) -> bool:
        return self.state in states

    # ================================
    # State Properties
    # ================================

    @property
    def is_pending(self) -> bool:
        return self.is_state(
            PaymentStatusType.PENDING
        )

    @property
    def is_successful(self) -> bool:
        return self.is_state(
            PaymentStatusType.SUCCESS
        )

    @property
    def is_failed(self) -> bool:
        return self.is_state(
            PaymentStatusType.FAILED
        )

    @property
    def is_terminal(self) -> bool:
        return self.in_state(
            PaymentStatusType.SUCCESS,
            PaymentStatusType.FAILED,
        )

    # ================================
    # Business Capabilities
    # ================================

    @property
    def can_consume(self) -> bool:
        """
        A successful payment may be consumed exactly once.
        """
        return (
            self.is_successful
            and not self.is_consumed
        )

    @property
    def can_refund(self) -> bool:
        """
        Refund eligibility.

        Current business rule:
            SUCCESS
                +
            CONSUMED
                +
            NOT REFUNDED
        """

        return (
            self.is_successful
            and self.is_consumed
            and not self.is_refunded
        )

    # ================================
    # Financial Snapshot
    # ================================

    def validate_financial_snapshot(
        self,
        *,
        amount: Decimal,
        currency: str,
    ) -> None:
        """
        Validate an external financial value against this Payment.
        This method NEVER mutates the Payment.
        Used by verification/reconciliation services.

        Example:
            payment.validate_financial_snapshot(
                amount=gateway_amount,
                currency=gateway_currency,
            )
        """

        normalized_amount = Decimal(
            str(amount)
        )

        if normalized_amount != self.amount:
            raise ValidationError(
                {
                    "amount": _(
                        "Payment amount does not match "
                        "the expected financial amount."
                    )
                }
            )

        if currency != self.currency:
            raise ValidationError(
                {
                    "currency": _(
                        "Payment currency does not match "
                        "the expected financial currency."
                    )
                }
            )

    # ================================
    # Domain Commands
    # ================================

    def succeed(self) -> "PaymentModel":
        """
        Transition Payment to SUCCESS.

        Allowed:
            PENDING -> SUCCESS

        Idempotent:
            SUCCESS -> SUCCESS

        Forbidden:
            FAILED -> SUCCESS

        IMPORTANT:
        This command changes only the Payment aggregate.

        It does NOT:
            - inspect PaymentAttempt
            - query gateway
            - mutate Order
            - dispatch events
            - save itself
        """

        if self.is_successful:
            return self

        self.require_pending()

        self._transition_to(
            PaymentStatusType.SUCCESS
        )

        return self

    def fail(self) -> "PaymentModel":
        """
        Transition Payment to FAILED.

        Allowed:

            PENDING -> FAILED

        Idempotent:

            FAILED -> FAILED

        Forbidden:

            SUCCESS -> FAILED
        """

        if self.is_failed:
            return self

        self.require_pending()

        self._transition_to(
            PaymentStatusType.FAILED
        )

        return self

    # ================================
    # Consumption
    # ================================

    def consume(self) -> "PaymentModel":
        """
        Consume the successful payment exactly once.

        Idempotent behavior:

            already consumed -> no-op

        Invalid:

            pending -> consume
            failed -> consume
        """

        if self.is_consumed:
            return self

        self.require_successful()
        self.require_not_consumed()

        self.is_consumed = True

        return self

    # ================================
    # Refund Marker
    # ================================

    def refund(self) -> "PaymentModel":
        """
        Mark Payment as refunded.

        IMPORTANT:

        This is NOT gateway refund execution.

        Gateway refund belongs to RefundService.

        This method records the aggregate-level business fact
        after the Refund workflow has successfully completed.
        """

        if self.is_refunded:
            return self

        self.require_refundable()

        self.is_refunded = True

        return self

    # ================================
    # Validation
    # ================================

    def clean(self) -> None:
        """
        Validate aggregate invariants.

        clean() is not a replacement for DB constraints.

        Database constraints remain authoritative for structural
        invariants.
        """

        super().clean()

        errors: dict[str, object] = {}

        # -----------------------------
        # Amount
        # -----------------------------

        if self.amount is None:
            errors["amount"] = _(
                "Payment amount is required."
            )

        elif self.amount <= Decimal("0"):
            errors["amount"] = _(
                "Payment amount must be greater than zero."
            )

        # -----------------------------
        # Currency
        # -----------------------------

        if not self.currency:
            errors["currency"] = _(
                "Payment currency is required."
            )

        # -----------------------------
        # Gateway
        # -----------------------------

        if not self.gateway:
            errors["gateway"] = _(
                "Payment gateway is required."
            )

        # -----------------------------
        # Version
        # -----------------------------

        if self.version < 1:
            errors["version"] = _(
                "Payment version must be greater than zero."
            )

        # -----------------------------
        # Consumed
        # -----------------------------

        if (
            self.is_consumed
            and not self.is_successful
        ):
            errors["is_consumed"] = _(
                "Only successful payments can be consumed."
            )

        # -----------------------------
        # Refunded
        # -----------------------------

        if (
            self.is_refunded
            and not self.is_successful
        ):
            errors["is_refunded"] = _(
                "Only successful payments can be refunded."
            )

        # -----------------------------
        # Refund requires consumption
        # -----------------------------

        if (
            self.is_refunded
            and not self.is_consumed
        ):
            errors["is_refunded"] = _(
                "Consumed payment required before refund."
            )

        if errors:
            raise ValidationError(
                errors
            )

    # ================================
    # Representation
    # ================================

    def __str__(self) -> str:
        return (
            f"Payment("
            f"id={self.pk}, "
            f"order={self.order_id}, "
            f"status={self.get_status_display()}, "
            f"amount={self.amount} "
            f"{self.currency}"
            f")"
        )

    def __repr__(self) -> str:
        return (
            f"<PaymentModel "
            f"id={self.pk} "
            f"status={self.state.name} "
            f"version={self.version}>"
        )

    # ================================
    # Guard API
    # ================================

    def _require(
        self,
        condition: bool,
        message: str,
    ) -> None:
        if not condition:
            raise ValidationError(
                message
            )

    def _require_state(
        self,
        state: PaymentStatusType,
    ) -> None:
        self._require(
            self.is_state(state),
            _(
                "Payment must be %(state)s."
            )
            % {
                "state": state.label,
            },
        )

    def _require_not_state(
        self,
        state: PaymentStatusType,
    ) -> None:
        self._require(
            not self.is_state(state),
            _(
                "Payment must not be %(state)s."
            )
            % {
                "state": state.label,
            },
        )

    # ================================
    # Transition Engine
    # ================================

    _ALLOWED_TRANSITIONS = {
        PaymentStatusType.PENDING: {
            PaymentStatusType.SUCCESS,
            PaymentStatusType.FAILED,
        },

        PaymentStatusType.SUCCESS: set(),

        PaymentStatusType.FAILED: set(),
    }

    def _transition_to(
        self,
        state: PaymentStatusType,
    ) -> None:
        """
        Execute one domain state transition.

        This method deliberately performs no persistence.
        """

        current = self.state

        # -----------------------------
        # Same state
        # -----------------------------

        if current == state:
            return

        # -----------------------------
        # Explicit transition contract
        # -----------------------------

        allowed = self._ALLOWED_TRANSITIONS.get(
            current,
            set(),
        )

        if state not in allowed:
            raise ValidationError(
                _(
                    "Invalid Payment transition: "
                    "%(source)s -> %(target)s."
                )
                % {
                    "source": current.label,
                    "target": state.label,
                }
            )

        self.status = state

    # ================================
    # Guards
    # ================================

    def require_pending(self) -> None:
        self._require_state(
            PaymentStatusType.PENDING
        )

    def require_successful(self) -> None:
        self._require_state(
            PaymentStatusType.SUCCESS
        )

    def require_failed(self) -> None:
        self._require_state(
            PaymentStatusType.FAILED
        )

    def require_consumed(self) -> None:
        self._require(
            self.is_consumed,
            _("Payment must be consumed."),
        )

    def require_not_consumed(self) -> None:
        self._require(
            not self.is_consumed,
            _("Payment already consumed."),
        )

    def require_refundable(self) -> None:
        self._require(
            self.can_refund,
            _("Payment cannot be refunded."),
        )

    def require_not_refunded(self) -> None:
        self._require(
            not self.is_refunded,
            _("Payment has already been refunded."),
        )

    def require_terminal(self) -> None:
        self._require(
            self.is_terminal,
            _("Payment must be finished."),
        )

    def require_not_terminal(self) -> None:
        self._require(
            not self.is_terminal,
            _("Payment is already finished."),
        )