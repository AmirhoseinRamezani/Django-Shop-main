# payment/models/payment_attempt.py
from __future__ import annotations

from typing import Optional

from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from payment.enums import PaymentAttemptStatus
from payment.managers import PaymentAttemptManager

class PaymentAttempt(models.Model):
    """
    Payment Attempt Aggregate Entity.

    A PaymentAttempt represents exactly one communication cycle
    between a Payment aggregate and its payment gateway.

    Example lifecycle:

        Payment
            │
            ├── Attempt #1 -> timeout
            ├── Attempt #2 -> failed
            └── Attempt #3 -> success

    Responsibilities
    ----------------
    PaymentAttempt is responsible for:

        - Tracking one gateway communication cycle.
        - Storing gateway-generated identifiers.
        - Tracking attempt state.
        - Tracking execution timing.
        - Tracking gateway response metadata.
        - Tracking technical failure information.
        - Exposing side-effect-free domain behavior.

    Explicitly NOT responsible for
    --------------------------------
    This model must NOT:

        - Execute database transactions.
        - Call payment gateways.
        - Perform HTTP requests.
        - Persist itself from domain methods.
        - Generate attempt numbers under concurrency.
        - Synchronize Payment.current_attempt.
        - Store raw gateway request/response payloads.
        - Implement repository logic.
        - Implement application workflow.

    Persistence and concurrency responsibilities belong to the
    Repository / Application Service layer.

    Gateway payloads belong to GatewayLog.
    """

    # ------------------------------
    # Identity
    # ------------------------------

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

    # ------------------------------
    # Gateway References
    # ------------------------------

    authority_id = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_index=True,
        help_text=_(
            "Gateway authority/token assigned to this payment attempt."
        ),
    )

    gateway_reference = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_index=True,
        help_text=_(
            "Gateway reference identifier returned after successful payment."
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

    # ------------------------------
    # Retry Chain
    # ------------------------------

    retry_of = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="retries",
        help_text=_(
            "Previous payment attempt from which this retry originated."
        ),
    )

    # ------------------------------
    # State
    # ------------------------------

    status = models.CharField(
        max_length=20,
        choices=PaymentAttemptStatus.choices,
        default=PaymentAttemptStatus.PENDING,
        db_index=True,
        help_text=_(
            "Current state of this payment gateway attempt."
        ),
    )

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
            "Human-readable gateway response message."
        ),
    )

    failure_reason = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=_(
            "Internal normalized reason for attempt failure."
        ),
    )

    # ------------------------------
    # Timing
    # ------------------------------

    started_at = models.DateTimeField(
        auto_now_add=True,
        help_text=_(
            "Timestamp when gateway communication started."
        ),
    )

    finished_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_(
            "Timestamp when this gateway attempt reached a terminal state."
        ),
    )

    latency_ms = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=_(
            "Measured gateway communication latency in milliseconds."
        ),
    )

    # ------------------------------
    # Request Context
    # ------------------------------

    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text=_(
            "Client IP address associated with this payment attempt."
        ),
    )

    user_agent = models.TextField(
        blank=True,
        default="",
        help_text=_(
            "Client user-agent associated with this payment attempt."
        ),
    )

    retry_count = models.PositiveSmallIntegerField(
        default=1,
        help_text=_(
            "Retry sequence count associated with this attempt."
        ),
    )

    # ------------------------------
    # Metadata
    # ------------------------------

    meta = models.JSONField(
        default=dict,
        blank=True,
        encoder=DjangoJSONEncoder,
        help_text=_(
            "Non-sensitive structured metadata associated with this attempt."
        ),
    )

    # ------------------------------
    # Manager
    # ------------------------------

    objects = PaymentAttemptManager()

    # ------------------------------
    # Meta
    # ------------------------------

    class Meta:
        ordering = (
            "-attempt_number",
            "-id",
        )

        constraints = [
            # -----------------------------------------------
            # One attempt number can exist only once per payment.
            #
            # Attempt number generation is still an application/repository
            # responsibility and must be concurrency-safe.
            # -----------------------------------------------
            models.UniqueConstraint(
                fields=[
                    "payment",
                    "attempt_number",
                ],
                name="payment_attempt_payment_number_uniq",
            ),

            # Attempt number must always be positive.
            models.CheckConstraint(
                condition=Q(attempt_number__gte=1),
                name="payment_attempt_number_positive",
            ),

            # A successful attempt must have a reference ID.
            models.CheckConstraint(
                condition=(
                    ~Q(status=PaymentAttemptStatus.SUCCESS)
                    | Q(gateway_reference__gt="")
                ),
                name="payment_attempt_success_requires_ref",
            ),

            # Terminal attempts must have a completion timestamp.
            # PENDING is the only non-terminal state.
            models.CheckConstraint(
                condition=(
                    ~Q(status=PaymentAttemptStatus.SUCCESS)
                    | Q(authority_id__gt="")
                ),
                name="payment_attempt_success_requires_authority",
            ),

            models.CheckConstraint(
                condition=Q(retry_count__gte=1),
                name="payment_attempt_retry_positive",
            ),

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

            # finished_at can never be earlier than started_at.
            models.CheckConstraint(
                condition=(
                    Q(finished_at__isnull=True)
                    |
                    Q(finished_at__gte=models.F("started_at"))
                ),
                name="payment_attempt_finish_after_start",
            ),
        ]

        indexes = [
            # Find the latest pending attempt for a payment.
            models.Index(
                fields=[
                    "payment",
                    "status",
                    "-attempt_number",
                ],
                name="pay_attempt_payment_status_idx",
            ),

            # Operational monitoring:
            # Find recent attempts by status.
            models.Index(
                fields=[
                    "status",
                    "-started_at",
                ],
                name="pay_attempt_status_started_idx",
            ),

            # Gateway reconciliation / callback lookup.
            models.Index(
                fields=[
                    "payment",
                    "gateway_reference",
                ],
                name="pay_attempt_payment_ref_idx",
            ),

            models.Index(
                fields=[
                    "payment",
                    "gateway_transaction_id",
                ],
                name="pay_attempt_payment_tx_idx",
            ),

            # Gateway authority lookup.
            models.Index(
                fields=[
                    "payment",
                    "authority_id",
                ],
                name="pay_attempt_payment_auth_idx",
            ),
        ]

    # ------------------------------
    # Validation
    # ------------------------------

    def clean(self) -> None:
        """
        Validate domain invariants.

        This method is intentionally side-effect free.
        """
        super().clean()
        self._validate_invariants()

    # ------------------------------
    # State Properties
    # ------------------------------

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
    def is_finished(self) -> bool:
        return (
            self.status != PaymentAttemptStatus.PENDING
            and self.finished_at is not None
        )

    @property
    def external_reference(self) -> Optional[str]:
        """
        Return the strongest available gateway reference.

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

    # ------------------------------
    # State Machine
    # ------------------------------

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

    # ------------------------------
    # Domain API
    # ------------------------------

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

        Characteristics:

            - Idempotent.
            - Persistence ignorant.
            - Financially immutable.
            - Supports late gateway transaction identifiers.
            - Rejects identity conflicts.
        """

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
            PaymentAttemptStatus.SUCCESS
        )

        authority_id = self._normalize(authority_id)

        self._require(
            bool(authority_id),
            _("Authority identifier is required for a successful attempt."),
        )

        self._assign_authority(authority_id)
        self._assign_reference(gateway_reference)
        self._assign_transaction(gateway_transaction_id)

        self._update_gateway_metadata(
            response_code=response_code,
            gateway_message=gateway_message,
        )

        self._finish(
            status=PaymentAttemptStatus.SUCCESS,
            latency_ms=latency_ms,
        )

        self.failure_reason = ""

        return self

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

        Duplicate callbacks/webhooks must never change the
        financial identity of an already successful attempt.
        """

        self._reconcile_authority(authority_id)
        self._reconcile_reference(gateway_reference)
        self._reconcile_transaction(gateway_transaction_id)

        self._update_gateway_metadata(
            response_code=response_code,
            gateway_message=gateway_message,
        )

        self._record_success_latency(latency_ms)

        self.failure_reason = ""

        return self

    # ------------------------------
    # Failure
    # ------------------------------

    def mark_failed(
        self,
        *,
        reason: str = "",
        response_code: str = "",
        gateway_message: str = "",
        latency_ms: int | None = None,
    ) -> "PaymentAttempt":
        """
        Mark the attempt as failed.
        """

        return self._mark_terminal(
            status=PaymentAttemptStatus.FAILED,
            reason=reason,
            response_code=response_code,
            gateway_message=gateway_message,
            latency_ms=latency_ms,
        )

    # ------------------------------
    # Timeout
    # ------------------------------

    def mark_timeout(
        self,
        *,
        reason: str = "",
        latency_ms: int | None = None,
    ) -> "PaymentAttempt":
        """
        Mark the attempt as timed out.
        """

        return self._mark_terminal(
            status=PaymentAttemptStatus.TIMEOUT,
            reason=reason,
            latency_ms=latency_ms,
        )

    # ------------------------------
    # Cancellation
    # ------------------------------

    def mark_cancelled(
        self,
        *,
        reason: str = "",
    ) -> "PaymentAttempt":
        """
        Mark the attempt as cancelled.
        """

        return self._mark_terminal(
            status=PaymentAttemptStatus.CANCELLED,
            reason=reason,
        )

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
        Transition the attempt to a terminal state.

        Transition validation happens before mutation.
        """

        self._require_transition(status)

        self._update_gateway_metadata(
            response_code=response_code,
            gateway_message=gateway_message,
        )

        self.failure_reason = self._normalize(reason)

        self._finish(
            status=status,
            latency_ms=latency_ms,
        )

        return self

    # ------------------------------
    # Gateway Metadata
    # ------------------------------

    def register_gateway_response(
        self,
        *,
        response_code: str = "",
        gateway_message: str = "",
    ) -> "PaymentAttempt":
        """
        Register normalized gateway response metadata.

        Raw gateway payload persistence belongs to GatewayLog.
        """

        self._require(
            self.is_pending,
            _(
                "Gateway response can only be registered "
                "for pending attempts."
            ),
        )

        self._update_gateway_metadata(
            response_code=response_code,
            gateway_message=gateway_message,
        )

        return self

    # ------------------------------
    # Latency
    # ------------------------------

    def record_latency(
        self,
        *,
        latency_ms: int | None = None,
    ) -> "PaymentAttempt":
        """
        Record explicit gateway latency.

        This method is intentionally side-effect free with respect
        to persistence.
        """

        if latency_ms is None:
            return self

        self._require(
            latency_ms >= 0,
            _("Latency cannot be negative."),
        )

        self.latency_ms = latency_ms

        return self

    # ------------------------------
    # Domain Helpers
    # ------------------------------

    def _assign_authority(
        self,
        authority_id: str,
    ) -> None:
        authority_id = self._normalize(authority_id)

        if not authority_id:
            return

        if not self.authority_id:
            self.authority_id = authority_id
            return

        self._require(
            self.authority_id == authority_id,
            _("Authority identifier conflict detected."),
        )

    def _assign_reference(
        self,
        gateway_reference: str,
    ) -> None:
        gateway_reference = self._normalize(gateway_reference)

        self._require(
            bool(gateway_reference),
            _("Gateway reference is required."),
        )

        if not self.gateway_reference:
            self.gateway_reference = gateway_reference
            return

        self._require(
            self.gateway_reference == gateway_reference,
            _("Gateway reference conflict detected."),
        )

    def _assign_transaction(
        self,
        gateway_transaction_id: str,
    ) -> None:
        gateway_transaction_id = self._normalize(
            gateway_transaction_id
        )

        if not gateway_transaction_id:
            return

        if not self.gateway_transaction_id:
            self.gateway_transaction_id = gateway_transaction_id
            return

        self._require(
            self.gateway_transaction_id == gateway_transaction_id,
            _(
                "Gateway transaction identifier conflict detected."
            ),
        )

    def _update_gateway_metadata(
        self,
        *,
        response_code: str,
        gateway_message: str,
    ) -> None:
        response_code = self._normalize(response_code)
        gateway_message = self._normalize(gateway_message)

        if response_code:
            self.response_code = response_code

        if gateway_message:
            self.gateway_message = gateway_message

    # ------------------------------
    # Identity Reconciliation
    # ------------------------------

    def _reconcile_authority(
        self,
        authority_id: str,
    ) -> None:
        """
        Reconcile authority identifier for an already successful attempt.

        Empty values are ignored because some gateways may omit
        the authority during verification callbacks.
        """

        authority_id = self._normalize(authority_id)

        if not authority_id:
            return

        self._assign_authority(authority_id)

    def _reconcile_reference(
        self,
        gateway_reference: str,
    ) -> None:
        """
        Gateway reference is immutable.
        """

        self._assign_reference(gateway_reference)

    def _reconcile_transaction(
        self,
        gateway_transaction_id: str,
    ) -> None:
        """
        Reconcile gateway transaction identifier.

        Some gateways provide the transaction identifier only
        during verification.
        """

        self._assign_transaction(gateway_transaction_id)

    # ------------------------------
    # Validation Helpers
    # ------------------------------

    def _validate_identity(self) -> None:
        """
        Validate gateway identity invariants.
        """

        if (
            self.status != PaymentAttemptStatus.SUCCESS
            and self.gateway_transaction_id
        ):
            raise ValidationError(
                {
                    "gateway_transaction_id": _(
                        "Only successful attempts may contain "
                        "a transaction identifier."
                    )
                }
            )

        if self.status == PaymentAttemptStatus.SUCCESS:
            errors = {}

            if not self.gateway_reference:
                errors["gateway_reference"] = _(
                    "Successful attempts require a gateway reference."
                )

            if not self.authority_id:
                errors["authority_id"] = _(
                    "Successful attempts require an authority identifier."
                )

            if self.failure_reason:
                errors["failure_reason"] = _(
                    "Successful attempts cannot contain "
                    "a failure reason."
                )

            if errors:
                raise ValidationError(errors)

        elif self.gateway_reference:
            raise ValidationError(
                {
                    "gateway_reference": _(
                        "Only successful attempts may have "
                        "a gateway reference."
                    )
                }
            )

    def _validate_retry(self) -> None:
        if self.retry_count < 1:
            raise ValidationError(
                {
                    "retry_count": _(
                        "Retry count must be greater than zero."
                    )
                }
            )

        if self.attempt_number < 1:
            raise ValidationError(
                {
                    "attempt_number": _(
                        "Attempt number must be greater than zero."
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

    def _validate_state(self) -> None:
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

        if self.finished_at is None:
            raise ValidationError(
                {
                    "finished_at": _(
                        "Completed attempts require "
                        "a finished timestamp."
                    )
                }
            )

    def _validate_invariants(self) -> None:
        """
        Validate every domain invariant.
        """

        self._validate_identity()
        self._validate_state()
        self._validate_dates()
        self._validate_retry()

    # ------------------------------
    # Latency Helpers
    # ------------------------------

    def _calculate_latency(
        self,
        *,
        finished_at,
    ) -> Optional[int]:
        """
        Calculate attempt latency from start and finish timestamps.
        """

        if self.started_at is None or finished_at is None:
            return None

        elapsed = finished_at - self.started_at

        return max(
            0,
            int(elapsed.total_seconds() * 1000),
        )

    def _record_latency(
        self,
        *,
        latency_ms: int | None,
        finished_at,
    ) -> None:
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
        Preserve the first successful latency measurement.
        """

        if self.latency_ms is not None:
            return

        self._record_latency(
            latency_ms=latency_ms,
            finished_at=self.finished_at,
        )

    # ------------------------------
    # Guards
    # ------------------------------

    @staticmethod
    def _normalize(value: str | None) -> str:
        return (value or "").strip()

    def _require(
        self,
        condition: bool,
        message: str,
    ) -> None:
        if not condition:
            raise ValidationError(message)

    # ------------------------------
    # Transition Helpers
    # ------------------------------

    def _require_transition(
        self,
        target: PaymentAttemptStatus,
    ) -> None:
        """
        Ensure the current state may transition to the target state.
        """

        allowed = self._ALLOWED_TRANSITIONS.get(
            self.status,
            set(),
        )

        self._require(
            target in allowed,
            _(
                "Transition from '%(current)s' to '%(target)s' "
                "is not allowed."
            )
            % {
                "current": self.status,
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
        Complete a valid state transition.
        """

        self._require_transition(status)

        finished_at = timezone.now()

        self.status = status
        self.finished_at = finished_at

        self._record_latency(
            latency_ms=latency_ms,
            finished_at=finished_at,
        )

    # ------------------------------
    # Representation
    # ------------------------------

    def __str__(self) -> str:
        return (
            f"Attempt("
            f"payment={self.payment_id}, "
            f"number={self.attempt_number}, "
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

