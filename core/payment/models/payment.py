# payment/models/payment.py
# ================================
# Imports
# ================================
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
# ================================
# Payment Aggregate Root
# ================================

class PaymentModel(models.Model):
    """
    Payment Aggregate Root.
    Responsibilities
    ----------------
    Payment owns:

        - Financial lifecycle
        - Payment state transitions
        - Consumption state
        - Refund state
        - Aggregate invariants

    Payment does NOT own:

        - Gateway communication
        - PaymentAttempt queries
        - Refund execution
        - Persistence
        - Transactions
        - Optimistic locking

    Infrastructure responsibilities belong to:

        Repository
            - Save
            - Lock
            - Version checking
            - Queries

        Service Layer
            - Workflow orchestration

        PaymentAttempt
            - Gateway execution lifecycle

        Refund
            - Refund lifecycle
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
            "Payment requested amount."
        ),
    )

    currency = models.CharField(
        max_length=8,
        choices=Currency.choices,
        default=Currency.IRR,
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
            "Optimistic concurrency version."
        ),
    )

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
                condition=(F("amount") > Decimal("0")),
                name="payment_amount_positive",
            ),
            models.CheckConstraint(
                condition=(F("version") >= 1),
                name="payment_version_positive",
            ),
        ]
        
    # ================================
    # Aggregate State
    # ================================

    @property
    def is_pending(self):
        """
        Aggregate is waiting for successful payment.
        """
        return self.is_state(
            PaymentStatusType.PENDING,
        )

    @property
    def is_successful(self):
        """
        Aggregate has been paid successfully.
        """
        return self.is_state(
            PaymentStatusType.SUCCESS,
        )

    @property
    def is_failed(self):
        """
        Aggregate has reached failure state.
        """
        return self.is_state(
            PaymentStatusType.FAILED,
        )

    @property
    def is_terminal(self):
        """
        Aggregate reached terminal state.
        """
        return self.in_state(
            PaymentStatusType.SUCCESS,
            PaymentStatusType.FAILED,
        )
    
    # ================================
    # State API
    # ================================
    @property
    def state(self) -> PaymentStatusType:
        # Current aggregate state.
        return PaymentStatusType(self.status)
    
    def is_state(
        self,
        state: PaymentStatusType,
    ) -> bool:
        # Returns whether aggregate is in the given state.
        return self.state == state

    def in_state(
        self,
        *states: PaymentStatusType,
    ) -> bool:
        """
        Returns whether aggregate belongs to one of
        the provided states.
        """
        return self.state in states

    # Business API
    @property
    def can_consume(self):

        return (
            self.is_successful
            and
            not self.is_consumed
        )
        
    @property
    def can_refund(self):

        return (
            self.is_successful
            and
            self.is_consumed
            and
            not self.is_refunded
        )
    
    # ================================
    # Aggregate Commands ~> Domain Entity
    # ================================

    def succeed(self) -> "PaymentModel":
        """
        Mark aggregate as successful.

        Existence of a successful PaymentAttempt
        must be verified by the Service Layer
        before invoking this command.
        """

        if self.is_successful:
            return self

        self.require_pending()
        
        self._transition_to(PaymentStatusType.SUCCESS)

        return self

    def fail(self):
        """
        Mark aggregate as failed.
        """
        if self.is_failed:
            return self

        self.require_pending()
        self._transition_to(PaymentStatusType.FAILED)

        return self

    def consume(self) -> "PaymentModel":
        """
        Consume payment exactly once.
        """
        if self.is_consumed:
            return self

        self.require_successful()
        self.require_not_consumed()
        
        self.is_consumed = True

        return self


    def refund(self) -> "PaymentModel":
        """
        Mark payment as refunded.

        Refund execution belongs to Refund.
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

        This method validates only business rules
        owned by the Payment aggregate.

        Persistence validation belongs to the
        Repository.
        """

        super().clean()

        if self.amount <= Decimal("0"):
            raise ValidationError(
                {
                    "amount": _("Payment amount must be greater than zero.")
                }
            )

        if (
            self.is_refunded
            and
            not self.is_successful
        ):
            raise ValidationError(
                {
                    "is_refunded": _(
                        "Only successful payments "
                        "can be refunded."
                    )
                }
            )
        if (
            self.is_consumed
            and
            not self.is_successful
        ):
            raise ValidationError(
                {
                    "is_consumed": _(
                        "Only successful payments "
                        "can be consumed."
                    )
                }
            )

        if (
            self.is_refunded
            and
            not self.is_consumed
        ):
            raise ValidationError(
                {
                    "is_refunded": _("Consumed payment required before refund.")
                }
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
            raise ValidationError(message)
        
    def _require_state(
        self,
        state: PaymentStatusType,
    ):

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
    ):
        self._require(
            not self.is_state(state),
            _("Payment must not be %(state)s.")
            % {"state": state.label},
        )

    # Transition Helper    
    def _transition_to(self, state: PaymentStatusType) -> None:
        if self.status == state:
            return
        if self.is_terminal:
            raise ValidationError(
                _("Payment is already finished.")
            )
        self.status = state
        # return self
    
    def require_pending(self):
        self._require_state(
            PaymentStatusType.PENDING,
        )

    def require_successful(self):
        self._require_state(
            PaymentStatusType.SUCCESS,
        )
    
    def require_failed(self):
        self._require_state(
            PaymentStatusType.FAILED,
        )

    def require_consumed(self):
        self._require(
            self.is_consumed,
            _("Payment must be consumed."),
        )

    def require_not_consumed(self):
        self._require(
            not self.is_consumed,
            _("Payment already consumed."),
        )

    def require_refundable(self):
        self._require(
            self.can_refund,
            _("Payment cannot be refunded."),
        )

    def require_not_refunded(self):
        self._require(
            not self.is_refunded,
            _("Payment has already been refunded."),
        )

    def require_terminal(self):

        self._require(
            self.is_terminal,
            _("Payment must be finished."),
        )


    def require_not_terminal(self):

        self._require(
            not self.is_terminal,
            _("Payment is already finished."),
        )
