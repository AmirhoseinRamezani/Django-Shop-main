# core/payment/models/payment.py
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from order.models import OrderModel
from payment.enums import Currency, PaymentGateway, PaymentStatusType
from payment.managers import PaymentManager


class PaymentModel(models.Model):
    """Payment aggregate root.

    The model owns only aggregate-local state and deterministic domain
    mutations. Persistence, locking, transactions, gateway calls, Order
    mutation and event dispatch remain outside the model.

    ``is_refunded`` means the Payment has been *fully* refunded. Partial
    refunds and the cumulative refundable balance belong to the Refund
    workflow and are evaluated while the Payment row is locked.
    """

    order = models.ForeignKey(
        OrderModel,
        on_delete=models.PROTECT,
        related_name="payments",
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        help_text=_("Immutable financial amount of this payment."),
    )

    currency = models.CharField(
        max_length=8,
        choices=Currency.choices,
        default=Currency.IRR,
        help_text=_("Immutable currency of this payment."),
    )

    gateway = models.CharField(
        max_length=32,
        choices=PaymentGateway.choices,
        db_index=True,
    )

    status = models.PositiveSmallIntegerField(
        choices=PaymentStatusType.choices,
        default=PaymentStatusType.PENDING,
        db_index=True,
    )

    version = models.PositiveIntegerField(
        default=1,
        help_text=_(
            "Optimistic concurrency version. The repository owns CAS persistence."
        ),
    )

    is_consumed = models.BooleanField(default=False)

    # This flag is deliberately retained for compatibility with the existing
    # schema. Its semantic meaning is now explicitly FULL refund only.
    is_refunded = models.BooleanField(
        default=False,
        help_text=_("True only when the Payment has been fully refunded."),
    )

    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    objects = PaymentManager()

    class Meta:
        verbose_name = _("Payment")
        verbose_name_plural = _("Payments")
        ordering = ("-created_date", "-id")

        indexes = [
            models.Index(fields=["status"], name="payment_status_idx"),
            models.Index(
                fields=["gateway", "status"],
                name="payment_gateway_status_idx",
            ),
            models.Index(
                fields=["order", "status"],
                name="payment_order_status_idx",
            ),
            models.Index(fields=["created_date"], name="payment_created_idx"),
        ]

        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=Decimal("0")),
                name="payment_amount_positive",
            ),
            models.CheckConstraint(
                condition=Q(version__gte=1),
                name="payment_version_positive",
            ),
            models.CheckConstraint(
                condition=Q(currency__gt=""),
                name="payment_currency_required",
            ),
            # One active Payment lifecycle per Order. Historical SUCCESS and
            # FAILED aggregates remain fully queryable and immutable.
            models.UniqueConstraint(
                fields=("order",),
                condition=Q(status=PaymentStatusType.PENDING),
                name="payment_one_pending_per_order",
            ),
        ]

    @property
    def state(self) -> PaymentStatusType:
        return PaymentStatusType(self.status)

    def is_state(self, state: PaymentStatusType) -> bool:
        return self.state == state

    def in_state(self, *states: PaymentStatusType) -> bool:
        return self.state in states

    @property
    def is_pending(self) -> bool:
        return self.is_state(PaymentStatusType.PENDING)

    @property
    def is_successful(self) -> bool:
        return self.is_state(PaymentStatusType.SUCCESS)

    @property
    def is_failed(self) -> bool:
        return self.is_state(PaymentStatusType.FAILED)

    @property
    def is_terminal(self) -> bool:
        return self.in_state(
            PaymentStatusType.SUCCESS,
            PaymentStatusType.FAILED,
        )

    @property
    def can_consume(self) -> bool:
        return self.is_successful and not self.is_consumed

    @property
    def can_refund(self) -> bool:
        """Return whether this Payment can participate in a refund.

        This intentionally does not require ``not is_refunded`` because
        partial/multiple refunds are valid. The Refund workflow must enforce
        the cumulative amount invariant under the Payment row lock.
        """
        return self.is_successful and self.is_consumed and not self.is_refunded

    @property
    def is_fully_refunded(self) -> bool:
        """Explicit alias for the historical ``is_refunded`` flag."""
        return self.is_refunded

    def validate_financial_snapshot(
        self,
        *,
        amount: Decimal,
        currency: str,
    ) -> None:
        normalized_amount = Decimal(str(amount))
        normalized_currency = str(currency or "").strip()

        if normalized_amount != self.amount:
            raise ValidationError(
                {"amount": _(
                    "Payment amount does not match the expected financial amount."
                )}
            )

        if normalized_currency != self.currency:
            raise ValidationError(
                {"currency": _(
                    "Payment currency does not match the expected financial currency."
                )}
            )

    def succeed(self) -> "PaymentModel":
        if self.is_successful:
            return self
        self.require_pending()
        self._transition_to(PaymentStatusType.SUCCESS)
        return self

    def fail(self) -> "PaymentModel":
        if self.is_failed:
            return self
        self.require_pending()
        self._transition_to(PaymentStatusType.FAILED)
        return self

    def consume(self) -> "PaymentModel":
        if self.is_consumed:
            return self
        self.require_successful()
        self.is_consumed = True
        return self

    def refund(self) -> "PaymentModel":
        """Record the aggregate fact that the Payment is fully refunded.

        Gateway execution and cumulative refund calculation are owned by the
        Refund application workflow. This command should be called only after
        that workflow has established that no refundable balance remains.
        """
        if self.is_refunded:
            return self
        self.require_successful()
        self.require_consumed()
        self.is_refunded = True
        return self

    def clean(self) -> None:
        super().clean()
        errors: dict[str, object] = {}

        if self.amount is None or self.amount <= Decimal("0"):
            errors["amount"] = _("Payment amount must be greater than zero.")
        if not self.currency:
            errors["currency"] = _("Payment currency is required.")
        if not self.gateway:
            errors["gateway"] = _("Payment gateway is required.")
        if self.version < 1:
            errors["version"] = _("Payment version must be greater than zero.")
        if self.is_consumed and not self.is_successful:
            errors["is_consumed"] = _(
                "Only successful payments can be consumed."
            )
        if self.is_refunded and not self.is_successful:
            errors["is_refunded"] = _(
                "Only successful payments can be refunded."
            )
        if self.is_refunded and not self.is_consumed:
            errors["is_refunded"] = _(
                "Consumed payment required before full refund."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return (
            f"Payment(id={self.pk}, order={self.order_id}, "
            f"status={self.get_status_display()}, amount={self.amount} "
            f"{self.currency})"
        )

    def __repr__(self) -> str:
        return (
            f"<PaymentModel id={self.pk} status={self.state.name} "
            f"version={self.version}>"
        )

    def _require(self, condition: bool, message: str) -> None:
        if not condition:
            raise ValidationError(message)

    def _require_state(self, state: PaymentStatusType) -> None:
        self._require(
            self.is_state(state),
            _("Payment must be %(state)s.") % {"state": state.label},
        )

    _ALLOWED_TRANSITIONS = {
        PaymentStatusType.PENDING: {
            PaymentStatusType.SUCCESS,
            PaymentStatusType.FAILED,
        },
        PaymentStatusType.SUCCESS: set(),
        PaymentStatusType.FAILED: set(),
    }

    def _transition_to(self, state: PaymentStatusType) -> None:
        current = self.state
        if current == state:
            return
        allowed = self._ALLOWED_TRANSITIONS.get(current, set())
        if state not in allowed:
            raise ValidationError(
                _(
                    "Invalid Payment transition: %(source)s -> %(target)s."
                ) % {"source": current.label, "target": state.label}
            )
        self.status = state

    def require_pending(self) -> None:
        self._require_state(PaymentStatusType.PENDING)

    def require_successful(self) -> None:
        self._require_state(PaymentStatusType.SUCCESS)

    def require_failed(self) -> None:
        self._require_state(PaymentStatusType.FAILED)

    def require_consumed(self) -> None:
        self._require(self.is_consumed, _("Payment must be consumed."))

    def require_not_consumed(self) -> None:
        self._require(not self.is_consumed, _("Payment already consumed."))

    def require_refundable(self) -> None:
        self._require(self.can_refund, _("Payment cannot be refunded."))

    def require_not_refunded(self) -> None:
        self._require(
            not self.is_refunded,
            _("Payment has already been fully refunded."),
        )

    def require_terminal(self) -> None:
        self._require(self.is_terminal, _("Payment must be finished."))

    def require_not_terminal(self) -> None:
        self._require(not self.is_terminal, _("Payment is already finished."))
