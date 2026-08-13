# core/payment/models/refund.py
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import F, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from payment.enums import RefundReason, RefundStatus
from payment.models.payment import PaymentModel


class Refund(models.Model):
    """
    Refund aggregate entity.

    A Refund represents one independent refund lifecycle belonging to a
    Payment aggregate.

    -------------------------------------
    Architectural boundary
    -------------------------------------

    Refund owns:

    - immutable financial snapshot;
    - currency snapshot;
    - request idempotency identity;
    - refund reason;
    - refund lifecycle state;
    - gateway identities;
    - gateway response evidence;
    - refund-local invariants;
    - deterministic state transitions;
    - refund-local observability data.

    Refund does NOT own:

    - transactions;
    - database locking;
    - repository access;
    - gateway HTTP calls;
    - cumulative refund calculation;
    - Payment mutation;
    - Order mutation;
    - retry orchestration;
    - event dispatching.

    Those responsibilities belong to the application/service layer.

    -------------------------------------
    Aggregate / concurrency rule
    -------------------------------------

    Refundable balance is a Payment-level aggregate invariant.

    The canonical workflow is:

        lock Payment
            ->
        verify Payment refund eligibility
            ->
        calculate successful refunded amount
            ->
        calculate refundable balance
            ->
        validate requested refund
            ->
        create/load idempotent Refund
            ->
        execute/reconcile gateway operation
            ->
        transition Refund
            ->
        mark Payment fully refunded if balance reaches zero
            ->
        create Outbox event
            ->
        commit

    The Payment row is the canonical concurrency boundary.

    -------------------------------------
    V1 financial policy
    -------------------------------------

    V1 intentionally uses:

        Decimal
        +
        immutable Payment currency snapshot

    No FX, Money object, fractional currency engine, crypto asset,
    blockchain network or exchange-rate snapshot is introduced here.

    Those concerns belong to V2 and should be additive.
    """

    # ================================
    # Aggregate relationship
    # ================================

    payment = models.ForeignKey(
        PaymentModel,
        on_delete=models.PROTECT,
        related_name="refunds",
        help_text=_(
            "Payment aggregate against which this refund belongs."
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
        help_text=_(
            "Immutable currency snapshot of the Payment."
        ),
    )

    # ================================
    # Idempotency
    # ================================

    idempotency_key = models.CharField(
        max_length=128,
        unique=True,
        help_text=_(
            "Application-level idempotency identity for this refund request."
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
    # Gateway evidence
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
            "Normalized internal or gateway failure reason."
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
            # -------------------------------------------
            # Financial invariants
            # -------------------------------------------

            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="refund_amount_positive",
            ),

            models.CheckConstraint(
                condition=Q(currency__gt=""),
                name="refund_currency_required",
            ),

            # -------------------------------------------
            # Idempotency invariants
            # -------------------------------------------

            models.CheckConstraint(
                condition=Q(idempotency_key__gt=""),
                name="refund_idempotency_key_required",
            ),

            # -------------------------------------------
            # Lifecycle invariants
            # -------------------------------------------

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

            # -------------------------------------------
            # SUCCESS invariants
            # -------------------------------------------

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

            # -------------------------------------------
            # FAILED invariants
            # -------------------------------------------

            models.CheckConstraint(
                condition=(
                    ~Q(status=RefundStatus.FAILED)
                    |
                    Q(failure_reason__gt="")
                ),
                name="refund_failed_requires_failure_reason",
            ),

            # -------------------------------------------
            # Gateway identity uniqueness
            # -------------------------------------------

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
    def external_reference(self) -> Optional[str]:
        """
        Return the strongest available gateway identity.

        Gateway transaction ID has precedence over gateway reference.
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
        Validate this refund against an already-loaded Payment snapshot.

        This method deliberately does not dereference ``self.payment``.

        Therefore it performs no implicit database query.

        Cumulative refund validation remains outside this entity and must
        be performed by the refund application workflow while the Payment
        row is locked.
        """

        errors: dict[str, object] = {}

        normalized_payment_amount = Decimal(
            str(payment_amount)
        )

        normalized_payment_currency = self._normalize(
            payment_currency
        )

        if self.amount is None:
            errors["amount"] = _(
                "Refund amount is required."
            )

        elif self.amount <= Decimal("0"):
            errors["amount"] = _(
                "Refund amount must be greater than zero."
            )

        elif self.amount > normalized_payment_amount:
            errors["amount"] = _(
                "Refund amount cannot exceed the original Payment amount."
            )

        if self.currency != normalized_payment_currency:
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
        Return whether this individual Refund equals the Payment amount.

        This does not determine aggregate refund completion.

        Example:

            Payment = 1,000,000

            Refund #1 = 600,000
            Refund #2 = 400,000

        Neither individual Refund is a full refund, while the aggregate
        Payment becomes fully refunded after both successful refunds.
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
        Transition:

            PENDING -> SUCCESS

        Repeated SUCCESS calls are reconciliation attempts.

        Existing terminal financial state is never blindly overwritten.
        """

        reference = self._normalize(
            gateway_reference
        )

        transaction_id = self._normalize(
            gateway_transaction_id
        )

        # ---------------------------------
        # Idempotent reconciliation
        # ---------------------------------

        if self.is_success:
            self._reconcile_success_identity(
                gateway_reference=reference,
                gateway_transaction_id=transaction_id,
            )

            return self

        # ---------------------------------
        # State guard
        # ---------------------------------

        self._require_transition(
            RefundStatus.SUCCESS
        )

        # ---------------------------------
        # Successful gateway operation must have an identity
        # ---------------------------------

        self._require(
            bool(reference or transaction_id),
            _(
                "A successful refund requires at least one gateway identity."
            ),
        )

        # ---------------------------------
        # Gateway identities
        # ---------------------------------

        self._assign_gateway_reference(
            reference
        )

        self._assign_gateway_transaction(
            transaction_id
        )

        # ---------------------------------
        # Gateway evidence
        # ---------------------------------

        self._update_gateway_metadata(
            response_code=response_code,
            gateway_message=gateway_message,
        )

        # ---------------------------------
        # SUCCESS cannot retain failure evidence
        # ---------------------------------

        self.failure_reason = ""

        # ---------------------------------
        # Terminal transition
        # ---------------------------------

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
        Transition:

            PENDING -> FAILED

        FAILED is terminal.

        Repeating the operation against an already failed Refund is a
        strict no-op and does not rewrite historical evidence.
        """

        if self.is_failed:
            return self

        normalized_reason = self._normalize(
            reason
        )

        self._require(
            bool(normalized_reason),
            _(
                "A failed refund requires a failure reason."
            ),
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
        Register non-terminal gateway evidence.

        Only PENDING refunds may receive mutable gateway evidence.

        Terminal financial records are historical facts.
        """

        self._require(
            self.is_pending,
            _(
                "Gateway response can only be registered "
                "for a pending refund."
            ),
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
        Validate identities supplied by a repeated successful callback
        or reconciliation attempt.

        Existing identities are never replaced.
        """

        if gateway_reference:
            self._require(
                bool(self.gateway_reference),
                _(
                    "Successful refund is missing its recorded "
                    "gateway reference."
                ),
            )

            self._require(
                self.gateway_reference == gateway_reference,
                _(
                    "Gateway refund reference conflict detected."
                ),
            )

        if gateway_transaction_id:
            self._require(
                bool(self.gateway_transaction_id),
                _(
                    "Successful refund is missing its recorded "
                    "gateway transaction identifier."
                ),
            )

            self._require(
                self.gateway_transaction_id
                == gateway_transaction_id,
                _(
                    "Gateway refund transaction identifier "
                    "conflict detected."
                ),
            )

    def _assign_gateway_reference(
        self,
        value: str,
    ) -> None:
        """
        Assign a gateway reference without allowing replacement.
        """

        if not value:
            return

        if not self.gateway_reference:
            self.gateway_reference = value
            return

        self._require(
            self.gateway_reference == value,
            _(
                "Gateway refund reference conflict detected."
            ),
        )

    def _assign_gateway_transaction(
        self,
        value: str,
    ) -> None:
        """
        Assign a gateway transaction identifier without allowing
        replacement.
        """

        if not value:
            return

        if not self.gateway_transaction_id:
            self.gateway_transaction_id = value
            return

        self._require(
            self.gateway_transaction_id == value,
            _(
                "Gateway refund transaction identifier "
                "conflict detected."
            ),
        )

    def _update_gateway_metadata(
        self,
        *,
        response_code: str = "",
        gateway_message: str = "",
    ) -> None:
        """
        Update non-financial gateway evidence.

        Empty incoming values never erase existing evidence.
        """

        normalized_code = self._normalize(
            response_code
        )

        normalized_message = self._normalize(
            gateway_message
        )

        if normalized_code:
            self.response_code = normalized_code

        if normalized_message:
            self.gateway_message = normalized_message

    # ================================
    # Lifecycle / latency
    # ================================

    def _calculate_latency(
        self,
        *,
        finished_at,
    ) -> Optional[int]:
        if (
            self.requested_at is None
            or finished_at is None
        ):
            return None

        elapsed = finished_at - self.requested_at

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
        """
        Calculate or record terminal operation latency.

        Terminal latency is intentionally not exposed through a public
        mutation method.
        """

        if latency_ms is None:
            self.latency_ms = self._calculate_latency(
                finished_at=finished_at,
            )
            return

        self._require(
            latency_ms >= 0,
            _("Latency cannot be negative."),
        )

        self.latency_ms = latency_ms

    # ================================
    # Validation
    # ================================

    def clean(self) -> None:
        super().clean()
        self._validate_invariants()

    def _validate_invariants(self) -> None:
        errors: dict[str, object] = {}

        # ---------------------------------
        # Financial invariants
        # ---------------------------------

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

        # ---------------------------------
        # Idempotency
        # ---------------------------------

        if not self._normalize(
            self.idempotency_key
        ):
            errors["idempotency_key"] = _(
                "Refund idempotency key is required."
            )

        # ---------------------------------
        # Lifecycle
        # ---------------------------------

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

        # ---------------------------------
        # SUCCESS invariants
        # ---------------------------------

        if self.is_success:
            if not (
                self.gateway_reference
                or self.gateway_transaction_id
            ):
                errors["gateway_reference"] = _(
                    "Successful refunds require at least one "
                    "gateway identity."
                )

            if self.failure_reason:
                errors["failure_reason"] = _(
                    "Successful refunds cannot contain a failure reason."
                )

        # ---------------------------------
        # FAILED invariants
        # ---------------------------------

        if self.is_failed and not self._normalize(
            self.failure_reason
        ):
            errors["failure_reason"] = _(
                "Failed refunds require a failure reason."
            )

        # ---------------------------------
        # Temporal consistency
        # ---------------------------------

        if (
            self.finished_at is not None
            and self.requested_at is not None
            and self.finished_at < self.requested_at
        ):
            errors["finished_at"] = _(
                "Finished time cannot be earlier than refund request time."
            )

        # ---------------------------------
        # Latency
        # ---------------------------------

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
        Enforce the Refund finite-state machine.
        """

        if self.status == target:
            return

        allowed = self._ALLOWED_TRANSITIONS.get(
            self.status,
            set(),
        )

        self._require(
            target in allowed,
            _(
                "Transition from '%(current)s' to "
                "'%(target)s' is not allowed."
            )
            % {
                "current": self.status,
                "target": target,
            },
        )

    def _finish(
        self,
        status: RefundStatus,
        *,
        latency_ms: int | None = None,
    ) -> None:
        """
        Perform a terminal state transition.

        Persistence remains the responsibility of the application
        workflow/repository.
        """

        self._require_transition(
            status
        )

        finished_at = timezone.now()

        self.status = status
        self.finished_at = finished_at

        self._record_latency(
            latency_ms=latency_ms,
            finished_at=finished_at,
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
            raise ValidationError(message)

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