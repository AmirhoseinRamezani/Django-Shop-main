# core/payment/models/payment_attempt.py
from __future__ import annotations

from typing import Optional

from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import F, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from payment.enums import PaymentAttemptStatus
from payment.managers import PaymentAttemptManager


class PaymentAttempt(models.Model):
    """
    Payment Attempt Aggregate Entity.

    A PaymentAttempt represents exactly one execution cycle between
    a Payment aggregate and its payment gateway.

    Example lifecycle:

        Payment
            │
            ├── Attempt #1 -> timeout
            ├── Attempt #2 -> failed
            └── Attempt #3 -> success

    Responsibilities
    ----------------
    PaymentAttempt is responsible for:

        - Tracking one gateway execution cycle.
        - Tracking gateway-generated identifiers.
        - Tracking attempt lifecycle state.
        - Tracking retry relationships.
        - Tracking execution timing and latency.
        - Tracking normalized gateway metadata.
        - Tracking client request context.
        - Exposing side-effect-free domain behavior.
        - Enforcing attempt-level invariants.

    Explicitly NOT responsible for
    --------------------------------
    This model must NOT:

        - Execute database transactions.
        - Call payment gateways.
        - Perform HTTP requests.
        - Persist itself from domain methods.
        - Generate attempt numbers under concurrency.
        - Synchronize Payment.current_attempt.
        - Implement repository logic.
        - Implement application workflow.
        - Store raw gateway request/response payloads.

    Persistence and concurrency responsibilities belong to the
    Repository / Application Service layer.

    Raw gateway payloads belong to GatewayLog.
    """

    # ------------------------------------
    # Identity
    # ------------------------------------

    payment = models.ForeignKey(
        "payment.PaymentModel",
        on_delete=models.CASCADE,
        related_name="attempts",
        help_text=_(
            "Payment aggregate that owns this attempt."
        ),
    )

    attempt_number = models.PositiveIntegerField(
        help_text=_(
            "Monotonically increasing attempt number within the payment."
        ),
    )

    # ------------------------------------
    # Gateway Identity
    # ------------------------------------

    authority_id = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_index=True,
        help_text=_(
            "Gateway authority/token assigned to this attempt."
        ),
    )

    gateway_reference = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_index=True,
        help_text=_(
            "Gateway reference assigned after successful execution."
        ),
    )

    gateway_transaction_id = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_index=True,
        help_text=_(
            "Gateway-side transaction identifier."
        ),
    )

    # ------------------------------------
    # Retry Chain
    # ------------------------------------

    retry_of = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="retries",
        help_text=_(
            "Historical attempt from which this retry originated."
        ),
    )

    retry_count = models.PositiveSmallIntegerField(
        default=1,
        help_text=_(
            "Retry sequence number represented by this attempt."
        ),
    )

    # ------------------------------------
    # Lifecycle
    # ------------------------------------

    status = models.CharField(
        max_length=20,
        choices=PaymentAttemptStatus.choices,
        default=PaymentAttemptStatus.PENDING,
        db_index=True,
        help_text=_(
            "Current lifecycle state of this payment attempt."
        ),
    )

    # ------------------------------------
    # Gateway Metadata
    # ------------------------------------

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
            "Internal normalized reason for technical/business failure."
        ),
    )

    # ------------------------------------
    # Timing
    # ------------------------------------

    started_at = models.DateTimeField(
        auto_now_add=True,
        help_text=_(
            "Timestamp at which this attempt execution started."
        ),
    )

    finished_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_(
            "Timestamp at which this attempt reached a terminal state."
        ),
    )

    latency_ms = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=_(
            "Measured execution latency in milliseconds."
        ),
    )

    # ------------------------------------
    # Request Context
    # ------------------------------------

    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text=_(
            "Client IP address associated with this attempt."
        ),
    )

    user_agent = models.TextField(
        blank=True,
        default="",
        help_text=_(
            "Client user-agent associated with this attempt."
        ),
    )

    # ------------------------------------
    # Safe Metadata
    # ------------------------------------

    meta = models.JSONField(
        default=dict,
        blank=True,
        encoder=DjangoJSONEncoder,
        help_text=_(
            "Non-sensitive structured metadata associated with this attempt."
        ),
    )

    # ------------------------------------
    # Manager
    # ------------------------------------

    objects = PaymentAttemptManager()

    # ------------------------------------
    # Meta
    # ------------------------------------

    class Meta:
        verbose_name = _("Payment Attempt")
        verbose_name_plural = _("Payment Attempts")

        ordering = (
            "-attempt_number",
            "-id",
        )

        constraints = [
            # --------------------------------
            # Attempt number
            # --------------------------------

            models.UniqueConstraint(
                fields=(
                    "payment",
                    "attempt_number",
                ),
                name="payment_attempt_payment_number_uniq",
            ),

            models.CheckConstraint(
                condition=Q(
                    attempt_number__gte=1,
                ),
                name="payment_attempt_number_positive",
            ),

            # --------------------------------
            # Retry
            # --------------------------------

            models.CheckConstraint(
                condition=Q(
                    retry_count__gte=1,
                ),
                name="payment_attempt_retry_positive",
            ),

            # --------------------------------
            # SUCCESS identity
            # --------------------------------

            models.CheckConstraint(
                condition=(
                    ~Q(
                        status=PaymentAttemptStatus.SUCCESS,
                    )
                    | Q(
                        gateway_reference__gt="",
                    )
                ),
                name="payment_attempt_success_requires_ref",
            ),

            models.CheckConstraint(
                condition=(
                    ~Q(
                        status=PaymentAttemptStatus.SUCCESS,
                    )
                    | Q(
                        authority_id__gt="",
                    )
                ),
                name="payment_attempt_success_requires_authority",
            ),

            # --------------------------------
            # Lifecycle / finished_at
            # --------------------------------

            models.CheckConstraint(
                condition=(
                    Q(
                        status=PaymentAttemptStatus.PENDING,
                        finished_at__isnull=True,
                    )
                    |
                    Q(
                        status__in=[
                            PaymentAttemptStatus.SUCCESS,
                            PaymentAttemptStatus.FAILED,
                            PaymentAttemptStatus.TIMEOUT,
                            PaymentAttemptStatus.CANCELLED,
                        ],
                        finished_at__isnull=False,
                    )
                ),
                name="payment_attempt_finished_state_valid",
            ),

            # --------------------------------
            # Finished time cannot precede start time
            # --------------------------------

            models.CheckConstraint(
                condition=(
                    Q(
                        finished_at__isnull=True,
                    )
                    |
                    Q(
                        finished_at__gte=F("started_at"),
                    )
                ),
                name="payment_attempt_finish_after_start",
            ),
        ]

        indexes = [
            models.Index(
                fields=(
                    "payment",
                    "status",
                    "-attempt_number",
                ),
                name="pay_attempt_payment_status_idx",
            ),

            models.Index(
                fields=(
                    "status",
                    "-started_at",
                ),
                name="pay_attempt_status_started_idx",
            ),

            models.Index(
                fields=(
                    "payment",
                    "gateway_reference",
                ),
                name="pay_attempt_payment_ref_idx",
            ),

            models.Index(
                fields=(
                    "payment",
                    "gateway_transaction_id",
                ),
                name="pay_attempt_payment_tx_idx",
            ),

            models.Index(
                fields=(
                    "payment",
                    "authority_id",
                ),
                name="pay_attempt_payment_auth_idx",
            ),

            models.Index(
                fields=(
                    "retry_of",
                ),
                name="pay_attempt_retry_of_idx",
            ),
        ]

    # ================================
    # STATE PROPERTIES
    # ================================

    @property
    def is_pending(self) -> bool:
        return self.status == PaymentAttemptStatus.PENDING

    @property
    def is_success(self) -> bool:
        return self.status == PaymentAttemptStatus.SUCCESS

    @property
    def is_failed(self) -> bool:
        return self.status == PaymentAttemptStatus.FAILED

    @property
    def is_timeout(self) -> bool:
        return self.status == PaymentAttemptStatus.TIMEOUT

    @property
    def is_cancelled(self) -> bool:
        return self.status == PaymentAttemptStatus.CANCELLED

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            PaymentAttemptStatus.SUCCESS,
            PaymentAttemptStatus.FAILED,
            PaymentAttemptStatus.TIMEOUT,
            PaymentAttemptStatus.CANCELLED,
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
        Return the strongest known gateway identity.

        Priority:
            gateway_transaction_id
                ↓
            gateway_reference
                ↓
            authority_id
        """

        return (
            self.gateway_transaction_id
            or self.gateway_reference
            or self.authority_id
            or None
        )

    # ================================
    # STATE MACHINE
    # ================================

    _ALLOWED_TRANSITIONS = {
        PaymentAttemptStatus.PENDING: {
            PaymentAttemptStatus.SUCCESS,
            PaymentAttemptStatus.FAILED,
            PaymentAttemptStatus.TIMEOUT,
            PaymentAttemptStatus.CANCELLED,
        },
        PaymentAttemptStatus.SUCCESS: set(),
        PaymentAttemptStatus.FAILED: set(),
        PaymentAttemptStatus.TIMEOUT: set(),
        PaymentAttemptStatus.CANCELLED: set(),
    }

    # ================================
    # SUCCESS
    # ================================

    def mark_success(
        self,
        *,
        authority_id: str,
        gateway_reference: str,
        gateway_transaction_id: str = "",
        response_code: str = "",
        gateway_message: str = "",
        latency_ms: int | None = None,
    ) -> "PaymentAttempt":
        """
        Transition this attempt to SUCCESS.

        Properties:

            - Idempotent.
            - Persistence ignorant.
            - Gateway identity is immutable.
            - Duplicate success notifications are reconciled.
            - Supports late gateway transaction identifiers.
        """

        # Explicit idempotency.
        if self.is_success:
            return self._merge_success(
                authority_id=authority_id,
                gateway_reference=gateway_reference,
                gateway_transaction_id=gateway_transaction_id,
                response_code=response_code,
                gateway_message=gateway_message,
                latency_ms=latency_ms,
            )

        self._require_transition(
            PaymentAttemptStatus.SUCCESS,
        )

        normalized_authority = self._normalize(
            authority_id,
        )

        normalized_reference = self._normalize(
            gateway_reference,
        )

        normalized_transaction = self._normalize(
            gateway_transaction_id,
        )

        self._require(
            bool(normalized_authority),
            _(
                "Authority identifier is required "
                "for a successful payment attempt."
            ),
        )

        self._require(
            bool(normalized_reference),
            _(
                "Gateway reference is required "
                "for a successful payment attempt."
            ),
        )

        self._assign_authority(
            normalized_authority,
        )

        self._assign_reference(
            normalized_reference,
        )

        self._assign_transaction(
            normalized_transaction,
        )

        self._update_gateway_metadata(
            response_code=response_code,
            gateway_message=gateway_message,
        )

        self.failure_reason = ""

        self._finish(
            status=PaymentAttemptStatus.SUCCESS,
            latency_ms=latency_ms,
        )

        return self

    # ================================
    # SUCCESS MERGE / IDEMPOTENCY
    # ================================

    def _merge_success(
        self,
        *,
        authority_id: str,
        gateway_reference: str,
        gateway_transaction_id: str,
        response_code: str,
        gateway_message: str,
        latency_ms: int | None,
    ) -> "PaymentAttempt":
        """
        Reconcile duplicate SUCCESS notifications.

        Existing financial identity is immutable.
        Conflicting identity is rejected.
        """

        self._reconcile_authority(
            authority_id,
        )

        self._reconcile_reference(
            gateway_reference,
        )

        self._reconcile_transaction(
            gateway_transaction_id,
        )

        self._update_gateway_metadata(
            response_code=response_code,
            gateway_message=gateway_message,
        )

        self._record_success_latency(
            latency_ms,
        )

        self.failure_reason = ""

        return self

    # ================================
    # FAILURE
    # ================================

    def mark_failed(
        self,
        *,
        reason: str = "",
        response_code: str = "",
        gateway_message: str = "",
        latency_ms: int | None = None,
    ) -> "PaymentAttempt":
        """
        Transition this attempt to FAILED.

        FAILED is terminal.
        """

        if self.is_failed:
            self._update_gateway_metadata(
                response_code=response_code,
                gateway_message=gateway_message,
            )

            if reason:
                self.failure_reason = self._normalize(
                    reason,
                )

            self._record_existing_terminal_latency(
                latency_ms,
            )

            return self

        return self._mark_terminal(
            status=PaymentAttemptStatus.FAILED,
            reason=reason,
            response_code=response_code,
            gateway_message=gateway_message,
            latency_ms=latency_ms,
        )

    # ================================
    # TIMEOUT
    # ================================

    def mark_timeout(
        self,
        *,
        reason: str = "",
        latency_ms: int | None = None,
    ) -> "PaymentAttempt":
        """
        Transition this attempt to TIMEOUT.

        TIMEOUT is terminal at the attempt level.

        A later gateway callback must be handled by the
        callback/reconciliation application workflow.
        """

        if self.is_timeout:
            if reason:
                self.failure_reason = self._normalize(
                    reason,
                )

            self._record_existing_terminal_latency(
                latency_ms,
            )

            return self

        return self._mark_terminal(
            status=PaymentAttemptStatus.TIMEOUT,
            reason=reason,
            latency_ms=latency_ms,
        )

    # ================================
    # CANCEL
    # ================================

    def mark_cancelled(
        self,
        *,
        reason: str = "",
    ) -> "PaymentAttempt":
        """
        Transition this attempt to CANCELLED.

        CANCELLED is terminal.
        """

        if self.is_cancelled:
            if reason:
                self.failure_reason = self._normalize(
                    reason,
                )

            return self

        return self._mark_terminal(
            status=PaymentAttemptStatus.CANCELLED,
            reason=reason,
        )

    # ================================
    # GENERIC TERMINAL TRANSITION
    # ================================

    def _mark_terminal(
        self,
        *,
        status: PaymentAttemptStatus,
        reason: str = "",
        response_code: str = "",
        gateway_message: str = "",
        latency_ms: int | None = None,
    ) -> "PaymentAttempt":
        """
        Transition from PENDING to a terminal state.
        """

        self._require_transition(
            status,
        )

        self._update_gateway_metadata(
            response_code=response_code,
            gateway_message=gateway_message,
        )

        self.failure_reason = self._normalize(
            reason,
        )

        self._finish(
            status=status,
            latency_ms=latency_ms,
        )

        return self

    # ================================
    # GATEWAY RESPONSE
    # ================================

    def register_gateway_response(
        self,
        *,
        response_code: str = "",
        gateway_message: str = "",
    ) -> "PaymentAttempt":
        """
        Register normalized gateway response metadata.

        Raw gateway payloads must be stored in GatewayLog.
        """

        self._require(
            self.is_pending,
            _(
                "Gateway response can only be registered "
                "for a pending payment attempt."
            ),
        )

        self._update_gateway_metadata(
            response_code=response_code,
            gateway_message=gateway_message,
        )

        return self

    # ================================
    # LATENCY
    # ================================

    def record_latency(
        self,
        *,
        latency_ms: int | None = None,
    ) -> "PaymentAttempt":
        """
        Record explicit execution latency.
        """

        if latency_ms is None:
            return self

        self._require(
            latency_ms >= 0,
            _("Latency cannot be negative."),
        )

        self.latency_ms = latency_ms

        return self

    def _calculate_latency(
        self,
        *,
        finished_at,
    ) -> Optional[int]:
        """
        Calculate latency from started_at to finished_at.
        """

        if (
            self.started_at is None
            or finished_at is None
        ):
            return None

        elapsed = finished_at - self.started_at

        return max(
            0,
            int(
                elapsed.total_seconds() * 1000,
            ),
        )

    def _record_latency(
        self,
        *,
        latency_ms: int | None,
        finished_at,
    ) -> None:
        """
        Record explicit latency or calculate it automatically.
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

    def _record_success_latency(
        self,
        latency_ms: int | None,
    ) -> None:
        """
        Preserve the first known terminal latency.
        """

        if self.latency_ms is not None:
            return

        self._record_latency(
            latency_ms=latency_ms,
            finished_at=self.finished_at,
        )

    def _record_existing_terminal_latency(
        self,
        latency_ms: int | None,
    ) -> None:
        """
        Preserve the original latency of a terminal attempt.
        """

        if self.latency_ms is not None:
            return

        self._record_latency(
            latency_ms=latency_ms,
            finished_at=self.finished_at,
        )

    # ================================
    # GATEWAY IDENTITY
    # ================================

    def _assign_authority(
        self,
        authority_id: str,
    ) -> None:
        """
        Assign gateway authority once.

        Existing authority is immutable.
        """

        normalized = self._normalize(
            authority_id,
        )

        if not normalized:
            return

        if not self.authority_id:
            self.authority_id = normalized
            return

        self._require(
            self.authority_id == normalized,
            _(
                "Authority identifier conflict detected."
            ),
        )

    def _assign_reference(
        self,
        gateway_reference: str,
    ) -> None:
        """
        Assign gateway reference once.

        Existing reference is immutable.
        """

        normalized = self._normalize(
            gateway_reference,
        )

        self._require(
            bool(normalized),
            _("Gateway reference is required."),
        )

        if not self.gateway_reference:
            self.gateway_reference = normalized
            return

        self._require(
            self.gateway_reference == normalized,
            _(
                "Gateway reference conflict detected."
            ),
        )

    def _assign_transaction(
        self,
        gateway_transaction_id: str,
    ) -> None:
        """
        Assign gateway transaction ID once.

        Existing transaction ID is immutable.
        """

        normalized = self._normalize(
            gateway_transaction_id,
        )

        if not normalized:
            return

        if not self.gateway_transaction_id:
            self.gateway_transaction_id = normalized
            return

        self._require(
            self.gateway_transaction_id == normalized,
            _(
                "Gateway transaction identifier conflict detected."
            ),
        )

    # ================================
    # GATEWAY METADATA
    # ================================

    def _update_gateway_metadata(
        self,
        *,
        response_code: str = "",
        gateway_message: str = "",
    ) -> None:
        """
        Update normalized gateway metadata.

        Empty incoming values never erase existing metadata.
        """

        normalized_code = self._normalize(
            response_code,
        )

        normalized_message = self._normalize(
            gateway_message,
        )

        if normalized_code:
            self.response_code = normalized_code

        if normalized_message:
            self.gateway_message = normalized_message

    # ================================
    # IDENTITY RECONCILIATION
    # ================================

    def _reconcile_authority(
        self,
        authority_id: str,
    ) -> None:
        normalized = self._normalize(
            authority_id,
        )

        if not normalized:
            return

        self._assign_authority(
            normalized,
        )

    def _reconcile_reference(
        self,
        gateway_reference: str,
    ) -> None:
        normalized = self._normalize(
            gateway_reference,
        )

        self._require(
            bool(normalized),
            _("Gateway reference is required."),
        )

        self._assign_reference(
            normalized,
        )

    def _reconcile_transaction(
        self,
        gateway_transaction_id: str,
    ) -> None:
        self._assign_transaction(
            gateway_transaction_id,
        )

    # ================================
    # VALIDATION
    # ================================

    def clean(self) -> None:
        """
        Validate all model/domain invariants.

        clean() does not replace database constraints.
        """

        super().clean()
        self._validate_invariants()

    def _validate_invariants(self) -> None:
        self._validate_identity()
        self._validate_state()
        self._validate_dates()
        self._validate_retry()
        self._validate_latency()
        self._validate_retry_chain()

    def _validate_identity(self) -> None:
        errors: dict[str, object] = {}
        
        # --------------------------------
        # Gateway transaction ID
        # --------------------------------

        if (
            self.gateway_transaction_id
            and self.status != PaymentAttemptStatus.SUCCESS
        ):
            errors["gateway_transaction_id"] = _(
                "Only successful attempts may contain "
                "a gateway transaction identifier."
            )

        # --------------------------------
        # SUCCESS identity
        # --------------------------------

        if self.status == PaymentAttemptStatus.SUCCESS:

            if not self.authority_id:
                errors["authority_id"] = _(
                    "Successful attempts require "
                    "an authority identifier."
                )

            if not self.gateway_reference:
                errors["gateway_reference"] = _(
                    "Successful attempts require "
                    "a gateway reference."
                )

            if self.failure_reason:
                errors["failure_reason"] = _(
                    "Successful attempts cannot contain "
                    "a failure reason."
                )

        # --------------------------------
        # Non-success reference
        # --------------------------------

        if (
            self.status != PaymentAttemptStatus.SUCCESS
            and self.gateway_reference
        ):
            errors["gateway_reference"] = _(
                "Only successful attempts may contain "
                "a gateway reference."
            )

        if errors:
            raise ValidationError(
                errors,
            )

    def _validate_state(self) -> None:
        """
        Validate lifecycle consistency.
        """

        if self.is_pending:
            if self.finished_at is not None:
                raise ValidationError(
                    {
                        "finished_at": _(
                            "Pending attempts cannot have "
                            "a finished timestamp."
                        )
                    }
                )

            return

        if not self.is_terminal:
            raise ValidationError(
                {
                    "status": _(
                        "Invalid payment attempt state."
                    )
                }
            )

        if self.finished_at is None:
            raise ValidationError(
                {
                    "finished_at": _(
                        "Terminal attempts require "
                        "a finished timestamp."
                    )
                }
            )

    def _validate_dates(self) -> None:
        if (
            self.finished_at is not None
            and self.started_at is not None
            and self.finished_at < self.started_at
        ):
            raise ValidationError(
                {
                    "finished_at": _(
                        "Finished time cannot be earlier "
                        "than started time."
                    )
                }
            )

    def _validate_retry(self) -> None:
        errors: dict[str, object] = {}

        if self.attempt_number < 1:
            errors["attempt_number"] = _(
                "Attempt number must be greater than zero."
            )

        if self.retry_count < 1:
            errors["retry_count"] = _(
                "Retry count must be greater than zero."
            )

        if errors:
            raise ValidationError(
                errors,
            )

    def _validate_retry_chain(self) -> None:
        """
        Validate retry relationship invariants.

        Retry semantics:

            First attempt:
                attempt_number = 1
                retry_count = 1
                retry_of = None

            Retry attempt N:
                attempt_number = N
                retry_count = N
                retry_of = attempt N-1

        The retry chain must remain inside the same Payment aggregate.

        This validation is intentionally model-level/domain validation.
        Persistence/concurrency guarantees belong to the repository/database
        layer and must not be implemented here.
        """

        # --------------------------------
        # First attempt
        # --------------------------------

        if self.retry_of_id is None:
            if self.attempt_number != 1:
                raise ValidationError(
                    {
                        "attempt_number": _(
                            "The first payment attempt must have "
                            "attempt number 1."
                        )
                    }
                )

            if self.retry_count != 1:
                raise ValidationError(
                    {
                        "retry_count": _(
                            "The first payment attempt must have "
                            "retry count 1."
                        )
                    }
                )

            return

        # --------------------------------
        # Retry attempt
        # --------------------------------

        if self.pk is not None and self.retry_of_id == self.pk:
            raise ValidationError(
                {
                    "retry_of": _(
                        "A payment attempt cannot retry itself."
                    )
                }
            )

        if self.attempt_number < 2:
            raise ValidationError(
                {
                    "attempt_number": _(
                        "A retry attempt must have an attempt number "
                        "greater than one."
                    )
                }
            )

        if self.retry_count != self.attempt_number:
            raise ValidationError(
                {
                    "retry_count": _(
                        "Retry count must match the attempt number."
                    )
                }
            )

        # --------------------------------
        # Unsaved retry parent
        # --------------------------------

        if not self.retry_of_id:
            return

        # --------------------------------
        # Load retry parent
        # --------------------------------

        try:
            previous_attempt = (
                type(self)
                .objects
                .only(
                    "id",
                    "payment_id",
                    "attempt_number",
                    "retry_count",
                )
                .get(
                    pk=self.retry_of_id,
                )
            )
        except type(self).DoesNotExist:
            raise ValidationError(
                {
                    "retry_of": _(
                        "The referenced retry attempt does not exist."
                    )
                }
            )

        # --------------------------------
        # Same Payment aggregate
        # --------------------------------

        if (
            self.payment_id is not None
            and previous_attempt.payment_id != self.payment_id
        ):
            raise ValidationError(
                {
                    "retry_of": _(
                        "A retry attempt must reference an attempt "
                        "belonging to the same payment."
                    )
                }
            )

        # --------------------------------
        # Sequential retry chain
        # --------------------------------

        expected_previous_attempt_number = (
            self.attempt_number - 1
        )

        if (
            previous_attempt.attempt_number
            != expected_previous_attempt_number
        ):
            raise ValidationError(
                {
                    "retry_of": _(
                        "A retry attempt must reference the "
                        "immediately previous payment attempt."
                    )
                }
            )

        # --------------------------------
        # Previous retry count consistency
        # --------------------------------

        if (
            previous_attempt.retry_count
            != self.retry_count - 1
        ):
            raise ValidationError(
                {
                    "retry_of": _(
                        "The retry chain contains an invalid "
                        "retry count sequence."
                    )
                }
            )
    def _validate_latency(self) -> None:
        if (
            self.latency_ms is not None
            and self.latency_ms < 0
        ):
            raise ValidationError(
                {
                    "latency_ms": _(
                        "Latency cannot be negative."
                    )
                }
            )

    # ================================
    # GUARDS
    # ================================

    @staticmethod
    def _normalize(
        value: str | None,
    ) -> str:
        return (
            value or ""
        ).strip()

    def _require(
        self,
        condition: bool,
        message: str,
    ) -> None:
        if not condition:
            raise ValidationError(
                message,
            )

    # ================================
    # TRANSITION HELPERS
    # ================================

    def _require_transition(
        self,
        target: PaymentAttemptStatus,
    ) -> None:
        """
        Validate a lifecycle transition.

        Same-state transitions are explicitly idempotent.
        """

        current = self.status

        if current == target:
            return

        allowed = self._ALLOWED_TRANSITIONS.get(
            current,
            set(),
        )

        self._require(
            target in allowed,
            _(
                "Transition from '%(current)s' to '%(target)s' "
                "is not allowed."
            )
            % {
                "current": current,
                "target": target,
            },
        )

    def _finish(
        self,
        *,
        status: PaymentAttemptStatus,
        latency_ms: int | None = None,
    ) -> None:
        """
        Finish the current attempt.

        This method only mutates the in-memory model.
        """

        self._require_transition(
            status,
        )

        finished_at = timezone.now()

        self.status = status
        self.finished_at = finished_at

        self._record_latency(
            latency_ms=latency_ms,
            finished_at=finished_at,
        )

    # ================================
    # REPRESENTATION
    # ================================

    def __str__(self) -> str:
        return (
            f"PaymentAttempt("
            f"payment={self.payment_id}, "
            f"attempt={self.attempt_number}, "
            f"status={self.get_status_display()}"
            f")"
        )

    def __repr__(self) -> str:
        return (
            "<PaymentAttempt "
            f"payment={self.payment_id} "
            f"attempt={self.attempt_number} "
            f"status={self.status!r}>"
        )