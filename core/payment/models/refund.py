# core/payment/models/refund.py
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import F, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from payment.enums import Currency, RefundReason, RefundStatus
from payment.exceptions import (
    PaymentCurrencyMismatchError,
    PaymentGatewayIdentityConflictError,
    PaymentInvalidTransitionError,
    PaymentInvariantViolation,
    PaymentRefundAmountInvalidError,
)
from payment.models.payment import PaymentModel


class Refund(models.Model):
    """
    Refund domain entity.

    A Refund represents exactly one refund financial lifecycle
    belonging to one Payment aggregate.

    Domain responsibilities:
        - refund financial snapshot
        - currency snapshot
        - request idempotency identity
        - refund classification
        - refund lifecycle
        - gateway identities
        - normalized gateway evidence
        - deterministic domain transitions
        - refund-local invariants

    Explicitly outside this model:
        - database transactions
        - row locking
        - repository access
        - gateway HTTP calls
        - cumulative refund calculation
        - Payment mutation
        - Order mutation
        - retries
        - task scheduling
        - event dispatching

    Aggregate-level refundable balance MUST be calculated by the
    application workflow while the canonical Payment row is locked.

    --------------------------------------------------
    V1 MONEY CONTRACT
    --------------------------------------------------

    V1 deliberately keeps money representation simple:

        Decimal
        +
        decimal_places=0
        +
        Payment currency snapshot

    The current platform calculates prices only in Iranian Rial.

    Therefore V1 does NOT introduce:

        - Money value objects
        - FX
        - exchange rates
        - fractional currency units
        - multi-currency arithmetic
        - crypto assets
        - currency conversion

    The currency field remains because the financial snapshot must be
    explicit and because the Payment Core is intended to evolve later.

    V1 invariant:

        Refund.currency == Payment.currency

    """

    # ================================
    # Aggregate relationship
    # ================================

    payment = models.ForeignKey(
        PaymentModel,
        on_delete=models.PROTECT,
        related_name="refunds",
        help_text=_(
            "Payment aggregate to which this refund belongs."
        ),
    )

    # ================================
    # Financial snapshot
    # ================================

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        help_text=_(
            "Immutable refund amount in the Payment currency."
        ),
    )

    currency = models.CharField(
        max_length=8,
        choices=Currency.choices,
        default=Currency.IRR,
        help_text=_(
            "Immutable currency snapshot of the Payment."
        ),
    )

    # ================================
    # Request idempotency
    # ================================

    idempotency_key = models.CharField(
        max_length=128,
        unique=True,
        help_text=_(
            "Stable idempotency identity for this refund request."
        ),
    )

    # ================================
    # Business classification
    # ================================

    reason = models.CharField(
        max_length=32,
        choices=RefundReason.choices,
        default=RefundReason.OTHER,
    )

    reason_detail = models.CharField(
        max_length=500,
        blank=True,
        default="",
    )

    # ================================
    # Lifecycle
    # ================================

    status = models.CharField(
        max_length=20,
        choices=RefundStatus.choices,
        default=RefundStatus.PENDING,
        db_index=True,
    )

    # ================================
    # Gateway identity
    # ================================

    gateway_reference = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_index=True,
        help_text=_(
            "Gateway-specific refund reference or authority."
        ),
    )

    gateway_transaction_id = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_index=True,
        help_text=_(
            "Gateway-specific refund transaction identifier."
        ),
    )

    # ================================
    # Normalized gateway evidence
    # ================================

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
            "Normalized refund failure reason."
        ),
    )

    # ================================
    # Lifecycle timestamps
    # ================================

    requested_at = models.DateTimeField(
        auto_now_add=True,
    )

    finished_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    # ================================
    # Observability
    # ================================

    latency_ms = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
    )

    user_agent = models.TextField(
        blank=True,
        default="",
    )

    meta = models.JSONField(
        default=dict,
        blank=True,
        encoder=DjangoJSONEncoder,
    )

    # ================================
    # Meta
    # ================================

    class Meta:
        verbose_name = _("Refund")
        verbose_name_plural = _("Refunds")

        ordering = (
            "-requested_at",
            "-id",
        )

        constraints = [
            # ------------------------------------
            # Financial invariants
            # ------------------------------------

            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="refund_amount_positive",
            ),

            models.CheckConstraint(
                condition=Q(currency__gt=""),
                name="refund_currency_required",
            ),

            # ------------------------------------
            # Idempotency
            # ------------------------------------

            models.CheckConstraint(
                condition=Q(idempotency_key__gt=""),
                name="refund_idempotency_key_required",
            ),

            # ------------------------------------
            # V1 currency
            #
            # V1 calculations are Rial-only.
            # Keeping this database-level prevents accidental creation
            # of unsupported currency refunds.
            # ------------------------------------

            models.CheckConstraint(
                condition=Q(currency=Currency.IRR),
                name="refund_v1_currency_irr",
            ),

            # ------------------------------------
            # Lifecycle
            # ------------------------------------

            models.CheckConstraint(
                condition=(
                    Q(
                        status=RefundStatus.PENDING,
                        finished_at__isnull=True,
                    )
                    |
                    Q(
                        status__in=(
                            RefundStatus.SUCCESS,
                            RefundStatus.FAILED,
                        ),
                        finished_at__isnull=False,
                    )
                ),
                name="refund_finished_state_valid",
            ),

            models.CheckConstraint(
                condition=(
                    Q(finished_at__isnull=True)
                    |
                    Q(finished_at__gte=F("requested_at"))
                ),
                name="refund_finish_after_request",
            ),

            # ------------------------------------
            # SUCCESS invariants
            # ------------------------------------

            models.CheckConstraint(
                condition=(
                    ~Q(status=RefundStatus.SUCCESS)
                    |
                    Q(gateway_reference__gt="")
                    |
                    Q(gateway_transaction_id__gt="")
                ),
                name="refund_success_requires_gateway_identity",
            ),

            models.CheckConstraint(
                condition=(
                    ~Q(status=RefundStatus.SUCCESS)
                    |
                    Q(failure_reason="")
                ),
                name="refund_success_no_failure_reason",
            ),

            # ------------------------------------
            # FAILED invariants
            # ------------------------------------

            models.CheckConstraint(
                condition=(
                    ~Q(status=RefundStatus.FAILED)
                    |
                    Q(failure_reason__gt="")
                ),
                name="refund_failed_requires_failure_reason",
            ),

            # ------------------------------------
            # Gateway identity uniqueness
            #
            # Scoped to Payment because the same gateway identifier
            # may theoretically exist under another payment context.
            # ------------------------------------

            models.UniqueConstraint(
                fields=(
                    "payment",
                    "gateway_reference",
                ),
                condition=Q(gateway_reference__gt=""),
                name="refund_payment_gateway_ref_uniq",
            ),

            models.UniqueConstraint(
                fields=(
                    "payment",
                    "gateway_transaction_id",
                ),
                condition=Q(gateway_transaction_id__gt=""),
                name="refund_payment_gateway_tx_uniq",
            ),
        ]

        indexes = [
            models.Index(
                fields=(
                    "payment",
                    "status",
                    "-requested_at",
                ),
                name="refund_payment_status_idx",
            ),
            models.Index(
                fields=(
                    "status",
                    "-requested_at",
                ),
                name="refund_status_requested_idx",
            ),
            models.Index(
                fields=(
                    "payment",
                    "-requested_at",
                ),
                name="refund_payment_requested_idx",
            ),
        ]

    # ================================
    # State helpers
    # ================================

    @property
    def is_pending(self) -> bool:
        return self.status == RefundStatus.PENDING

    @property
    def is_success(self) -> bool:
        return self.status == RefundStatus.SUCCESS

    @property
    def is_failed(self) -> bool:
        return self.status == RefundStatus.FAILED

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            RefundStatus.SUCCESS,
            RefundStatus.FAILED,
        }

    @property
    def is_finished(self) -> bool:
        return (
            self.is_terminal
            and self.finished_at is not None
        )

    @property
    def external_reference(self) -> str | None:
        """
        Return the strongest available gateway identity.

        Transaction ID takes precedence over gateway reference.
        """

        return (
            self.gateway_transaction_id
            or self.gateway_reference
            or None
        )

    # ================================
    # Financial validation
    # ================================

    def validate_against_payment(
        self,
        *,
        payment_amount: Decimal,
        payment_currency: str,
    ) -> None:
        """
        Validate this Refund against a loaded Payment snapshot.
        No relation access occurs here.

        No:
            - query
            - transaction
            - lock
            - repository access
            - cumulative refund calculation

        The cumulative invariant belongs to the application workflow
        while the Payment row is locked.
        """
        errors: dict[str, object] = {}

        payment_amount = Decimal(
            str(payment_amount)
        )

        payment_currency = self._normalize(
            payment_currency
        )

        # Payment itself must be financially valid.
        if payment_amount <= Decimal("0"):
            raise PaymentInvariantViolation(
                "Payment amount must be greater than zero."
            )

        # Refund amount must be positive.
        if self.amount is None:
            errors["amount"] = _(
                "Refund amount is required."
            )

        elif self.amount <= Decimal("0"):
            errors["amount"] = _(
                "Refund amount must be greater than zero."
            )

        # Individual refund may never exceed Payment.
        elif self.amount > payment_amount:
            errors["amount"] = _(
                "Refund amount cannot exceed the original Payment amount."
            )

        # Currency must match the Payment snapshot.
        if self.currency != payment_currency:
            errors["currency"] = _(
                "Refund currency must match the Payment currency."
            )

        if errors:
            raise ValidationError(errors)

    def is_full_payment_refund(
        self,
        *,
        payment_amount: Decimal,
    ) -> bool:
        """
        Return whether this individual Refund equals Payment amount.
        This does NOT determine aggregate full-refund status.

        Example:
            Payment   = 1,000,000
            Refund #1 =   600,000
            Refund #2 =   400,000

        The Payment becomes fully refunded only after the successful
        cumulative refund amount reaches Payment.amount.
        """

        return self.amount == Decimal(
            str(payment_amount)
        )

    # ================================
    # Domain transitions
    # ================================

    def mark_success(
        self,
        *,
        gateway_reference: str = "",
        gateway_transaction_id: str = "",
        response_code: str = "",
        gateway_message: str = "",
        latency_ms: int | None = None,
    ) -> "Refund":
        """
        PENDING -> SUCCESS.
        Repeated SUCCESS processing is idempotent.
        Existing gateway identities are never silently replaced.
        """

        reference = self._normalize(
            gateway_reference
        )

        transaction_id = self._normalize(
            gateway_transaction_id
        )

        # --------------------------------------------
        # Already successful = idempotent reconciliation
        # --------------------------------------------

        if self.is_success:
            self._reconcile_success_identity(
                gateway_reference=reference,
                gateway_transaction_id=transaction_id,
            )
            return self

        # --------------------------------------------
        # Only PENDING may become SUCCESS.
        # --------------------------------------------

        self._require_transition(
            RefundStatus.SUCCESS
        )

        # --------------------------------------------
        # Successful refund requires gateway identity.
        # --------------------------------------------

        if not (reference or transaction_id):
            raise PaymentInvariantViolation(
                "A successful refund requires at least one gateway identity."
            )

        # --------------------------------------------
        # Gateway identity assignment.
        # --------------------------------------------

        self._assign_gateway_reference(
            reference
        )

        self._assign_gateway_transaction(
            transaction_id
        )

        # --------------------------------------------
        # Gateway evidence.
        # --------------------------------------------

        self._update_gateway_metadata(
            response_code=response_code,
            gateway_message=gateway_message,
        )

        # SUCCESS cannot retain failure evidence.
        self.failure_reason = ""

        # --------------------------------------------
        # Terminal transition.
        # --------------------------------------------

        self._finish(
            RefundStatus.SUCCESS,
            latency_ms=latency_ms,
        )

        return self

    def mark_failed(
        self,
        *,
        reason: str = "",
        response_code: str = "",
        gateway_message: str = "",
        latency_ms: int | None = None,
    ) -> "Refund":
        """
        PENDING -> FAILED.
        FAILED is terminal.
        Repeated FAILED processing is an idempotent no-op.
        """

        # --------------------------------------------
        # Already failed = idempotent no-op.
        # --------------------------------------------

        if self.is_failed:
            return self

        normalized_reason = self._normalize(
            reason
        )

        if not normalized_reason:
            raise PaymentInvariantViolation(
                "A failed refund requires a failure reason."
            )

        self._require_transition(
            RefundStatus.FAILED
        )

        self._update_gateway_metadata(
            response_code=response_code,
            gateway_message=gateway_message,
        )

        self.failure_reason = normalized_reason

        self._finish(
            RefundStatus.FAILED,
            latency_ms=latency_ms,
        )

        return self

    def register_gateway_response(
        self,
        *,
        response_code: str = "",
        gateway_message: str = "",
    ) -> "Refund":
        """
        Record non-terminal gateway evidence.
        Only PENDING refunds may receive mutable gateway evidence.
        Terminal refunds are historical financial facts.
        """

        if not self.is_pending:
            raise PaymentInvalidTransitionError(
                (
                    "Gateway response can only be registered "
                    "for a pending refund."
                ),
                source_state=str(self.status),
                target_state=str(self.status),
            )

        self._update_gateway_metadata(
            response_code=response_code,
            gateway_message=gateway_message,
        )

        return self

    # ================================
    # Gateway identity reconciliation
    # ================================

    def _reconcile_success_identity(
        self,
        *,
        gateway_reference: str,
        gateway_transaction_id: str,
    ) -> None:
        """
        Reconcile identities for an already-successful Refund.

        Rules:
            stored A + incoming A -> OK
            stored A + incoming B -> conflict
            stored empty + incoming A -> enrich
            stored A + incoming empty -> OK
            both empty -> OK
        """

        self._reconcile_identity_value(
            field_name="gateway_reference",
            current=self.gateway_reference,
            incoming=gateway_reference,
        )

        self._reconcile_identity_value(
            field_name="gateway_transaction_id",
            current=self.gateway_transaction_id,
            incoming=gateway_transaction_id,
        )

    def _reconcile_identity_value(
        self,
        *,
        field_name: str,
        current: str,
        incoming: str,
    ) -> None:
        if not incoming:
            return

        if not current:
            setattr(
                self,
                field_name,
                incoming,
            )
            return

        if current != incoming:
            raise PaymentGatewayIdentityConflictError(
                "Gateway refund identity conflict detected.",
                details={
                    "refund_id": self.pk,
                    "identity": field_name,
                },
            )

    def _assign_gateway_reference(
        self,
        value: str,
    ) -> None:
        if not value:
            return

        if not self.gateway_reference:
            self.gateway_reference = value
            return

        if self.gateway_reference != value:
            raise PaymentGatewayIdentityConflictError(
                "Gateway refund reference conflict detected.",
                details={
                    "refund_id": self.pk,
                    "identity": "gateway_reference",
                },
            )

    def _assign_gateway_transaction(
        self,
        value: str,
    ) -> None:
        if not value:
            return

        if not self.gateway_transaction_id:
            self.gateway_transaction_id = value
            return

        if self.gateway_transaction_id != value:
            raise PaymentGatewayIdentityConflictError(
                "Gateway refund transaction identifier conflict detected.",
                details={
                    "refund_id": self.pk,
                    "identity": "gateway_transaction_id",
                },
            )

    def _update_gateway_metadata(
        self,
        *,
        response_code: str = "",
        gateway_message: str = "",
    ) -> None:
        """
        Update normalized gateway evidence.
        Empty values never erase existing evidence.
        """

        response_code = self._normalize(
            response_code
        )

        gateway_message = self._normalize(
            gateway_message
        )

        if response_code:
            self.response_code = response_code

        if gateway_message:
            self.gateway_message = gateway_message

    # ================================
    # Lifecycle / latency
    # ================================

    def _calculate_latency(
        self,
        *,
        finished_at,
    ) -> int | None:
        if (
            self.requested_at is None
            or finished_at is None
        ):
            return None

        elapsed = (
            finished_at - self.requested_at
        )

        return max(
            0,
            int(
                elapsed.total_seconds() * 1000
            ),
        )

    def _record_latency(
        self,
        *,
        latency_ms: int | None,
        finished_at,
    ) -> None:
        if latency_ms is None:
            self.latency_ms = self._calculate_latency(
                finished_at=finished_at
            )
            return

        if latency_ms < 0:
            raise PaymentInvariantViolation(
                "Latency cannot be negative."
            )

        self.latency_ms = latency_ms

    def _finish(
        self,
        status: RefundStatus,
        *,
        latency_ms: int | None = None,
    ) -> None:
        """
        Complete a terminal transition.
        Persistence remains outside the domain model.
        """

        self._require_transition(status)

        finished_at = timezone.now()

        self.status = status
        self.finished_at = finished_at

        self._record_latency(
            latency_ms=latency_ms,
            finished_at=finished_at,
        )

    # ================================
    # Validation
    # ================================

    def clean(self) -> None:
        super().clean()
        self._validate_invariants()

    def _validate_invariants(self) -> None:
        errors: dict[str, object] = {}

        # --------------------------------------------
        # Financial
        # --------------------------------------------

        if (
            self.amount is None
            or self.amount <= Decimal("0")
        ):
            errors["amount"] = _(
                "Refund amount must be greater than zero."
            )

        if not self._normalize(self.currency):
            errors["currency"] = _(
                "Refund currency is required."
            )

        # V1 only supports Rial.
        if (
            self.currency
            and self.currency != Currency.IRR
        ):
            errors["currency"] = _(
                "V1 refunds must use Iranian Rial."
            )

        # --------------------------------------------
        # Idempotency
        # --------------------------------------------

        if not self._normalize(
            self.idempotency_key
        ):
            errors["idempotency_key"] = _(
                "Refund idempotency key is required."
            )

        # --------------------------------------------
        # Lifecycle
        # --------------------------------------------

        if self.is_pending:
            if self.finished_at is not None:
                errors["finished_at"] = _(
                    "Pending refunds cannot have a finished timestamp."
                )

        elif self.is_terminal:
            if self.finished_at is None:
                errors["finished_at"] = _(
                    "Terminal refunds require a finished timestamp."
                )

        else:
            errors["status"] = _(
                "Invalid refund state."
            )

        # --------------------------------------------
        # SUCCESS
        # --------------------------------------------

        if self.is_success:
            if not (
                self.gateway_reference
                or self.gateway_transaction_id
            ):
                errors["gateway_reference"] = _(
                    "Successful refunds require at least one gateway identity."
                )

            if self.failure_reason:
                errors["failure_reason"] = _(
                    "Successful refunds cannot contain a failure reason."
                )

        # --------------------------------------------
        # FAILED
        # --------------------------------------------

        if (
            self.is_failed
            and not self._normalize(
                self.failure_reason
            )
        ):
            errors["failure_reason"] = _(
                "Failed refunds require a failure reason."
            )

        # --------------------------------------------
        # Temporal consistency
        # --------------------------------------------

        if (
            self.finished_at is not None
            and self.requested_at is not None
            and self.finished_at < self.requested_at
        ):
            errors["finished_at"] = _(
                "Finished time cannot be earlier than refund request time."
            )

        # --------------------------------------------
        # Latency
        # --------------------------------------------

        if (
            self.latency_ms is not None
            and self.latency_ms < 0
        ):
            errors["latency_ms"] = _(
                "Latency cannot be negative."
            )

        if errors:
            raise ValidationError(errors)

    # ================================
    # State machine
    # ================================

    _ALLOWED_TRANSITIONS = {
        RefundStatus.PENDING: {
            RefundStatus.SUCCESS,
            RefundStatus.FAILED,
        },
        RefundStatus.SUCCESS: set(),
        RefundStatus.FAILED: set(),
    }

    def _require_transition(
        self,
        target: RefundStatus,
    ) -> None:
        """
        Closed Refund state machine:
            PENDING -> SUCCESS
            PENDING -> FAILED

        Terminal states cannot be resurrected.
        Same-state idempotency is handled by public domain commands.
        """

        if self.status == target:
            return

        allowed = self._ALLOWED_TRANSITIONS.get(
            self.status,
            set(),
        )

        if target not in allowed:
            raise PaymentInvalidTransitionError(
                (
                    "Invalid Refund transition: "
                    f"{self.status} -> {target}."
                ),
                source_state=str(self.status),
                target_state=str(target),
            )

    # ================================
    # Utilities
    # ================================

    @staticmethod
    def _normalize(
        value: str | None,
    ) -> str:
        return (value or "").strip()

    @staticmethod
    def _require(
        condition: bool,
        message: str,
    ) -> None:
        if not condition:
            raise PaymentInvariantViolation(
                message
            )

    # ================================
    # Representation
    # ================================

    def __str__(self) -> str:
        return (
            f"Refund("
            f"id={self.pk}, "
            f"payment={self.payment_id}, "
            f"amount={self.amount} "
            f"{self.currency}, "
            f"status={self.get_status_display()}"
            f")"
        )

    def __repr__(self) -> str:
        return (
            f"<Refund "
            f"id={self.pk} "
            f"payment={self.payment_id} "
            f"amount={self.amount} "
            f"currency={self.currency!r} "
            f"status={self.status!r}>"
        )