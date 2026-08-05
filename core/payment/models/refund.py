# payment/models/refund.py
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Optional

from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from payment.enums import (
    Currency,
    PaymentGateway,
    RefundStatus,
    RefundReason,
)
from payment.managers import RefundManager


class Refund(models.Model):
    """
    Refund Domain Entity.
    A Refund belongs to exactly one Payment aggregate.
    Architecture
    ------------
    Payment
        ├── PaymentAttempt
        ├── Refund #1
        ├── Refund #2
        └── Refund #N

    Responsibilities
    ----------------
    Refund is responsible for:

        - Representing one refund operation.
        - Maintaining refund lifecycle state.
        - Validating refund amount.
        - Maintaining gateway-generated refund identifiers.
        - Enforcing successful-state invariants.
        - Providing side-effect-free domain behavior.
        - Supporting idempotent success/failure transitions.

    Refund is NOT responsible for:

        - Calculating whether the Payment is fully refunded.
        - Aggregating other refunds.
        - Querying the database.
        - Executing transactions.
        - Locking Payment or Refund rows.
        - Performing optimistic locking.
        - Calling payment gateways.
        - Storing raw gateway payloads.
        - Creating GatewayLog records.
        - Saving itself from domain methods.

    Persistence
    -----------
    Repository/Application Service is responsible for:

        - database transactions;
        - select_for_update();
        - optimistic locking;
        - refund amount aggregation;
        - persistence;
        - GatewayLog creation;
        - OutboxEvent creation.

    Gateway Payloads
    ----------------
    Raw gateway request/response payloads MUST NOT be stored here.
    They belong exclusively to GatewayLog.
    """

    # =========================
    # Identity
    # =========================

    payment = models.ForeignKey(
        "payment.PaymentModel",
        on_delete=models.PROTECT,
        related_name="refunds",
        help_text=_(
            "Payment aggregate that owns this refund."
        ),
    )

    # =========================
    # Idempotency
    # =========================

    idempotency_key = models.UUIDField(
        unique=True,
        editable=False,
        default=uuid.uuid4,
        help_text=_(
            "Unique application-level idempotency key for this refund."
        ),
    )

    # =========================
    # Financial
    # =========================

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        validators=[
            MinValueValidator(
                Decimal("1"),
            ),
        ],
        help_text=_(
            "Amount requested for this individual refund."
        ),
    )

    currency = models.CharField(
        max_length=8,
        choices=Currency.choices,
        help_text=_(
            "Currency of the refund amount."
        ),
    )

    # =========================
    # Gateway Context
    # =========================

    gateway = models.CharField(
        max_length=32,
        choices=PaymentGateway.choices,
        db_index=True,
        help_text=_(
            "Payment gateway responsible for processing this refund."
        ),
    )

    # =========================
    # State
    # =========================

    status = models.CharField(
        max_length=20,
        choices=RefundStatus.choices,
        default=RefundStatus.PENDING,
        db_index=True,
        help_text=_(
            "Current lifecycle state of this refund."
        ),
    )

    # =========================
    # Gateway Identifiers
    # =========================
    #
    # These fields contain normalized gateway identifiers only.
    #
    # Raw gateway payloads MUST NOT be stored here.
    # Raw request/response data belongs exclusively to GatewayLog.
    #
    # Once SUCCESS, existing gateway identifiers are immutable.
    # =========================

    gateway_ref = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_index=True,
        help_text=_(
            "Gateway-generated refund reference identifier."
        ),
    )

    gateway_transaction_id = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_index=True,
        help_text=_(
            "Gateway-side transaction identifier for the refund."
        ),
    )

    # =========================
    # Gateway Result
    # =========================

    response_code = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text=_(
            "Normalized gateway response code."
        ),
    )

    gateway_message = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=_(
            "Normalized gateway response message."
        ),
    )

    failure_reason = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=_(
            "Internal normalized reason for refund failure."
        ),
    )
    
    reason = models.CharField(
        max_length=32,
        choices=RefundReason.choices,
        default=RefundReason.OTHER,
    )

    # =========================
    # Lifecycle Timestamps
    # ========================
    
    requested_at = models.DateTimeField(
        auto_now_add=True,
        editable=False,
        help_text=_(
            "Timestamp when the refund entity was created."
        ),
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_(
            "Timestamp when the refund reached SUCCESS."
        ),
    )

    failed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_(
            "Timestamp when the refund reached FAILED."
        ),
    )

    # =========================
    # Metadata
    # =========================

    meta = models.JSONField(
        default=dict,
        blank=True,
        encoder=DjangoJSONEncoder,
        help_text=_(
            "Non-sensitive structured metadata associated with this refund."
        ),
    )

    # =========================
    # Audit Timestamps
    # =========================

    created_date = models.DateTimeField(
        auto_now_add=True,
        editable=False,
    )

    updated_date = models.DateTimeField(
        auto_now=True,
    )

    # =========================
    # Manager
    # =========================

    objects = RefundManager()

    # =========================
    # Meta
    # =========================

    class Meta:
        ordering = (
            "-created_date",
            "-id",
        )

        constraints = [

            # -----------------------------------------------
            # Refund amount must always be positive.
            # -----------------------------------------------
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="refund_amount_positive",
            ),

            # -----------------------------------------------
            # Successful refund must have gateway reference.
            # -----------------------------------------------
            models.CheckConstraint(
                condition=(
                    ~Q(status=RefundStatus.SUCCESS)
                    | Q(gateway_ref__gt="")
                ),
                name="refund_success_requires_gateway_ref",
            ),

            # -----------------------------------------------
            # Successful refund must have completion timestamp.
            # -----------------------------------------------
            models.CheckConstraint(
                condition=(
                    ~Q(status=RefundStatus.SUCCESS)
                    | Q(completed_at__isnull=False)
                ),
                name="refund_success_requires_completed_at",
            ),

            # -----------------------------------------------
            # Failed refund must have failure timestamp.
            # -----------------------------------------------
            models.CheckConstraint(
                condition=(
                    ~Q(status=RefundStatus.FAILED)
                    | Q(failed_at__isnull=False)
                ),
                name="refund_failed_requires_failed_at",
            ),

            # -----------------------------------------------
            # Pending refund cannot have terminal timestamps.
            # -----------------------------------------------
            models.CheckConstraint(
                condition=(
                    ~Q(status=RefundStatus.PENDING)
                    | (
                        Q(completed_at__isnull=True)
                        & Q(failed_at__isnull=True)
                    )
                ),
                name="refund_pending_has_no_terminal_timestamp",
            ),

            # -----------------------------------------------
            # Successful refund cannot have failure timestamp.
            # -----------------------------------------------
            models.CheckConstraint(
                condition=(
                    ~Q(status=RefundStatus.SUCCESS)
                    | Q(failed_at__isnull=True)
                ),
                name="refund_success_has_no_failed_at",
            ),

            # -----------------------------------------------
            # Failed refund cannot have completion timestamp.
            # -----------------------------------------------
            models.CheckConstraint(
                condition=(
                    ~Q(status=RefundStatus.FAILED)
                    | Q(completed_at__isnull=True)
                ),
                name="refund_failed_has_no_completed_at",
            ),

        ]

        indexes = [

            # -----------------------------------------------
            # Payment refund history.
            # -----------------------------------------------
            models.Index(
                fields=[
                    "payment",
                    "-created_date",
                ],
                name="refund_payment_created_idx",
            ),

            # -----------------------------------------------
            # Payment refund state queries.
            # -----------------------------------------------
            models.Index(
                fields=[
                    "payment",
                    "status",
                    "-created_date",
                ],
                name="refund_payment_status_idx",
            ),

            # -----------------------------------------------
            # Payment successful refund aggregation.
            #
            # Application/Repository can efficiently query:
            #
            # payment.refunds.successful()
            # -----------------------------------------------
            models.Index(
                fields=[
                    "payment",
                    "status",
                    "currency",
                ],
                name="refund_payment_success_idx",
            ),

            # -----------------------------------------------
            # Gateway reconciliation.
            # -----------------------------------------------
            models.Index(
                fields=[
                    "gateway",
                    "gateway_ref",
                ],
                name="refund_gateway_ref_idx",
            ),

            models.Index(
                fields=[
                    "gateway",
                    "gateway_transaction_id",
                ],
                name="refund_gateway_tx_idx",
            ),

            # -----------------------------------------------
            # Operational monitoring.
            # -----------------------------------------------
            models.Index(
                fields=[
                    "status",
                    "-created_date",
                ],
                name="refund_status_created_idx",
            ),

            # -----------------------------------------------
            # Gateway + status operational queries.
            # -----------------------------------------------
            models.Index(
                fields=[
                    "gateway",
                    "status",
                    "-created_date",
                ],
                name="refund_gateway_status_idx",
            ),
        ]

    # =========================
    # Validation
    # =========================

    def clean(self) -> None:
        """
        Validate Refund invariants.
        This method is intentionally side-effect free.

        It:
            - Does not query the database.
            - Does not save the entity.
            - Does not perform network operations.
            - Does not calculate aggregate refund totals.
            - Does not inspect other refunds.
        """

        super().clean()

        # ----------------------
        # Amount
        # ----------------------

        if self.amount <= Decimal("0"):
            raise ValidationError(
                {
                    "amount": _(
                        "Refund amount must be greater than zero."
                    )
                }
            )

        # ----------------------
        # Currency
        # ----------------------

        if not self.currency:
            raise ValidationError(
                {
                    "currency": _(
                        "Refund currency is required."
                    )
                }
            )

        # ----------------------
        # Gateway
        # ----------------------

        if not self.gateway:
            raise ValidationError(
                {
                    "gateway": _(
                        "Refund gateway is required."
                    )
                }
            )

        # ----------------------
        # SUCCESS invariants
        # ----------------------

        if self.is_success:

            if not self.gateway_ref:
                raise ValidationError(
                    {
                        "gateway_ref": _(
                            "A successful refund requires "
                            "a gateway reference."
                        )
                    }
                )

            if self.completed_at is None:
                raise ValidationError(
                    {
                        "completed_at": _(
                            "A successful refund requires "
                            "a completion timestamp."
                        )
                    }
                )

            if self.failed_at is not None:
                raise ValidationError(
                    {
                        "failed_at": _(
                            "A successful refund cannot have "
                            "a failure timestamp."
                        )
                    }
                )

        # ----------------------
        # FAILED invariants
        # ----------------------

        if self.is_failed:

            if self.failed_at is None:
                raise ValidationError(
                    {
                        "failed_at": _(
                            "A failed refund requires "
                            "a failure timestamp."
                        )
                    }
                )

            if self.completed_at is not None:
                raise ValidationError(
                    {
                        "completed_at": _(
                            "A failed refund cannot have "
                            "a completion timestamp."
                        )
                    }
                )

        # ----------------------
        # PENDING invariants
        # ----------------------

        if self.is_pending:

            if self.completed_at is not None:
                raise ValidationError(
                    {
                        "completed_at": _(
                            "A pending refund cannot have "
                            "a completion timestamp."
                        )
                    }
                )

            if self.failed_at is not None:
                raise ValidationError(
                    {
                        "failed_at": _(
                            "A pending refund cannot have "
                            "a failure timestamp."
                        )
                    }
                )

    # =========================
    # Persistence
    # =========================

    def save(self, *args, **kwargs):
        """
        Persist the Refund entity.

        Domain methods NEVER call save().

        The Repository/Application layer is responsible for:

            - atomic transactions;
            - row locking;
            - optimistic locking;
            - persistence;
            - GatewayLog creation;
            - OutboxEvent creation.

        Note:
            Refund itself does not implement optimistic locking because
            concurrency control belongs to the Repository layer.
        """

        self.full_clean()

        return super().save(
            *args,
            **kwargs,
        )

    # =========================
    # State Properties
    # =========================

    @property
    def is_pending(self) -> bool:
        """Return True when the refund is still pending."""

        return self.status == RefundStatus.PENDING

    @property
    def is_success(self) -> bool:
        """Return True when the refund completed successfully."""

        return self.status == RefundStatus.SUCCESS

    @property
    def is_failed(self) -> bool:
        """Return True when the refund permanently failed."""

        return self.status == RefundStatus.FAILED

    @property
    def is_finished(self) -> bool:
        """
        Return True when the refund reached a terminal state.
        """

        return self.is_success or self.is_failed

    @property
    def gateway_reference(self) -> Optional[str]:
        """
        Return the strongest available gateway identifier.

        Priority:

            gateway_transaction_id
                ↓
            gateway_ref
                ↓
            None
        """

        return (
            self.gateway_transaction_id
            or self.gateway_ref
            or None
        )

    # =========================
    # Domain: Can Complete
    # =========================

    def can_complete(self) -> bool:
        """
        Return whether this Refund can transition to SUCCESS.

        This method intentionally checks only the Refund itself.

        It MUST NOT:

            - Query Payment.
            - Query other Refunds.
            - Calculate remaining refundable amount.
            - Determine full refund state.

        The caller/application service must validate aggregate-level
        refund eligibility before invoking mark_success().
        """

        return self.is_pending

    # =========================
    # Domain: Mark Success
    # =========================

    def mark_success(
        self,
        *,
        gateway_ref: str,
        gateway_transaction_id: str = "",
        response_code: str = "",
        gateway_message: str = "",
    ) -> "Refund":
        """
        Mark this refund as successful.

        Idempotency
        -----------
        Calling this method multiple times with the same gateway
        identifiers is safe.

        Immutability
        ------------
        Existing gateway identifiers cannot be changed after SUCCESS.

        Persistence
        -----------
        This method NEVER calls save().

        The caller must persist the mutated entity through the
        repository/application layer.
        """

        normalized_gateway_ref = str(
            gateway_ref or ""
        ).strip()

        normalized_gateway_transaction_id = str(
            gateway_transaction_id or ""
        ).strip()

        normalized_response_code = str(
            response_code or ""
        ).strip()

        normalized_gateway_message = str(
            gateway_message or ""
        ).strip()

        # ----------------------
        # A successful refund always requires a gateway reference.
        # ----------------------

        if not normalized_gateway_ref:
            raise ValidationError(
                {
                    "gateway_ref": _(
                        "A successful refund requires "
                        "a gateway reference."
                    )
                }
            )

        # ----------------------
        # Idempotent SUCCESS.
        # ----------------------

        if self.is_success:

            # Existing gateway reference is immutable.
            if (
                self.gateway_ref
                and self.gateway_ref
                != normalized_gateway_ref
            ):
                raise ValidationError(
                    _(
                        "Gateway reference cannot be changed "
                        "after refund success."
                    )
                )

            # Existing transaction ID is immutable.
            if (
                self.gateway_transaction_id
                and normalized_gateway_transaction_id
                and (
                    self.gateway_transaction_id
                    != normalized_gateway_transaction_id
                )
            ):
                raise ValidationError(
                    _(
                        "Gateway transaction ID cannot be changed "
                        "after refund success."
                    )
                )

            # -----------------------------------------------
            # Allow enrichment when an identifier was previously
            # unavailable, but never overwrite an existing value.
            # -----------------------------------------------

            if (
                not self.gateway_ref
                and normalized_gateway_ref
            ):
                self.gateway_ref = (
                    normalized_gateway_ref
                )

            if (
                not self.gateway_transaction_id
                and normalized_gateway_transaction_id
            ):
                self.gateway_transaction_id = (
                    normalized_gateway_transaction_id
                )

            if normalized_response_code:
                self.response_code = (
                    normalized_response_code
                )

            if normalized_gateway_message:
                self.gateway_message = (
                    normalized_gateway_message
                )

            return self

        # ----------------------
        # FAILED is terminal.
        # ----------------------

        if self.is_failed:
            raise ValidationError(
                _(
                    "A failed refund cannot be marked "
                    "as successful."
                )
            )

        # ----------------------
        # Pending is the only state allowed to complete.
        # ----------------------

        if not self.can_complete():
            raise ValidationError(
                _(
                    "Refund cannot be completed."
                )
            )

        now = timezone.now()

        self.status = RefundStatus.SUCCESS

        self.gateway_ref = (
            normalized_gateway_ref
        )

        self.gateway_transaction_id = (
            normalized_gateway_transaction_id
        )

        self.response_code = (
            normalized_response_code
        )

        self.gateway_message = (
            normalized_gateway_message
        )

        self.failure_reason = ""

        self.completed_at = now

        self.failed_at = None

        return self

    # =========================
    # Domain: Mark Failed
    # =========================

    def mark_failed(
        self,
        *,
        reason: str = "",
        response_code: str = "",
        gateway_message: str = "",
    ) -> "Refund":
        """
        Mark the refund as failed.

        Idempotency
        -----------
        Calling this method on an already failed refund is safe.

        Terminal State
        --------------
        A successful refund can never transition to FAILED.

        Persistence
        -----------
        This method NEVER calls save().
        """

        # ----------------------
        # SUCCESS is immutable/terminal.
        # ----------------------

        if self.is_success:
            raise ValidationError(
                _(
                    "A successful refund cannot be marked "
                    "as failed."
                )
            )

        # ----------------------
        # Idempotent FAILED transition.
        # ----------------------

        if self.is_failed:
            return self

        now = timezone.now()

        self.status = RefundStatus.FAILED

        self.failure_reason = str(
            reason or ""
        ).strip()

        self.response_code = str(
            response_code or ""
        ).strip()

        self.gateway_message = str(
            gateway_message or ""
        ).strip()

        self.failed_at = now

        self.completed_at = None

        return self

    # =========================
    # Representation
    # =========================

    def __str__(self) -> str:
        return (
            f"Refund<"
            f"payment={self.payment_id}, "
            f"amount={self.amount}, "
            f"currency={self.currency}, "
            f"status={self.status}"
            f">"
        )
