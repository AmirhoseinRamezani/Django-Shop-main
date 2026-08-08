# payment/models/payment_attempt.py
from __future__ import annotations

from typing import ClassVar

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
    Payment gateway execution attempt.

    A PaymentAttempt represents exactly one gateway execution
    cycle belonging to a Payment aggregate.

    Example:

        Payment
            ├── Attempt #1 -> TIMEOUT
            ├── Attempt #2 -> FAILED
            └── Attempt #3 -> SUCCESS

    Responsibilities
    ----------------
    - Track one gateway execution lifecycle.
    - Store gateway identifiers.
    - Track attempt state.
    - Track execution timing.
    - Track normalized gateway metadata.
    - Track technical failure information.
    - Track callback reception.

    This model intentionally does NOT:

    - perform database transactions;
    - acquire database locks;
    - call gateways;
    - perform HTTP requests;
    - save itself;
    - generate attempt numbers;
    - execute retry workflows;
    - synchronize Payment state;
    - store raw gateway payloads;
    - contain repository queries.

    Persistence and concurrency belong to repositories/services.

    Raw gateway request/response payloads belong to GatewayLog.
    """

    # ------------------------------------------------------------------
    # Constants
    # ------------------------------------------------------------------

    MAX_ID_LENGTH: ClassVar[int] = 128
    MAX_RESPONSE_CODE_LENGTH: ClassVar[int] = 64
    MAX_MESSAGE_LENGTH: ClassVar[int] = 255

    TERMINAL_STATUSES: ClassVar[frozenset[str]] = frozenset(
        {
            PaymentAttemptStatus.SUCCESS,
            PaymentAttemptStatus.FAILED,
            PaymentAttemptStatus.TIMEOUT,
            PaymentAttemptStatus.CANCELLED,
        }
    )

    ALLOWED_TRANSITIONS: ClassVar[
        dict[str, frozenset[str]]
    ] = {
        PaymentAttemptStatus.PENDING: frozenset(
            {
                PaymentAttemptStatus.SUCCESS,
                PaymentAttemptStatus.FAILED,
                PaymentAttemptStatus.TIMEOUT,
                PaymentAttemptStatus.CANCELLED,
            }
        ),
        PaymentAttemptStatus.SUCCESS: frozenset(),
        PaymentAttemptStatus.FAILED: frozenset(),
        PaymentAttemptStatus.TIMEOUT: frozenset(),
        PaymentAttemptStatus.CANCELLED: frozenset(),
    }

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

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
            "Monotonically increasing attempt number "
            "within the payment."
        ),
    )

    # ------------------------------------------------------------------
    # Gateway Identity
    # ------------------------------------------------------------------

    authority_id = models.CharField(
        max_length=MAX_ID_LENGTH,
        blank=True,
        default="",
        help_text=_(
            "Gateway authority or authorization identifier."
        ),
    )

    gateway_reference = models.CharField(
        max_length=MAX_ID_LENGTH,
        blank=True,
        default="",
        help_text=_(
            "Gateway-provided payment reference."
        ),
    )

    gateway_transaction_id = models.CharField(
        max_length=MAX_ID_LENGTH,
        blank=True,
        default="",
        help_text=_(
            "Gateway-side transaction identifier."
        ),
    )

    # ------------------------------------------------------------------
    # Retry Chain
    # ------------------------------------------------------------------

    retry_of = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="retries",
        help_text=_(
            "Previous attempt from which this retry originated."
        ),
    )

    retry_count = models.PositiveSmallIntegerField(
        default=0,
        help_text=_(
            "Retry depth of this attempt. "
            "The initial attempt has value 0."
        ),
    )

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    status = models.CharField(
        max_length=20,
        choices=PaymentAttemptStatus.choices,
        default=PaymentAttemptStatus.PENDING,
        db_index=True,
        help_text=_(
            "Current gateway execution state."
        ),
    )

    response_code = models.CharField(
        max_length=MAX_RESPONSE_CODE_LENGTH,
        blank=True,
        default="",
        help_text=_(
            "Normalized gateway response code."
        ),
    )

    gateway_message = models.CharField(
        max_length=MAX_MESSAGE_LENGTH,
        blank=True,
        default="",
        help_text=_(
            "Normalized gateway response message."
        ),
    )

    failure_reason = models.CharField(
        max_length=MAX_MESSAGE_LENGTH,
        blank=True,
        default="",
        help_text=_(
            "Normalized internal failure reason."
        ),
    )

    # ------------------------------------------------------------------
    # Timing
    # ------------------------------------------------------------------

    started_at = models.DateTimeField(
        auto_now_add=True,
        help_text=_(
            "Timestamp when this attempt started."
        ),
    )

    finished_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_(
            "Timestamp when this attempt reached a terminal state."
        ),
    )

    latency_ms = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=_(
            "Gateway execution latency in milliseconds."
        ),
    )

    callback_received_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_(
            "Timestamp when a gateway callback was received."
        ),
    )

    # ------------------------------------------------------------------
    # Request Context
    # ------------------------------------------------------------------

    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text=_(
            "Client IP associated with this attempt."
        ),
    )

    user_agent = models.TextField(
        blank=True,
        default="",
        help_text=_(
            "Client user-agent associated with this attempt."
        ),
    )

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    meta = models.JSONField(
        default=dict,
        blank=True,
        encoder=DjangoJSONEncoder,
        help_text=_(
            "Non-sensitive structured metadata."
        ),
    )

    # ------------------------------------------------------------------
    # Manager
    # ------------------------------------------------------------------

    objects = PaymentAttemptManager()

    # ------------------------------------------------------------------
    # Meta
    # ------------------------------------------------------------------

    class Meta:
        verbose_name = _("Payment Attempt")
        verbose_name_plural = _("Payment Attempts")

        ordering = (
            "-attempt_number",
            "-id",
        )

        constraints = [
            # ----------------------------------------------------------
            # Attempt identity
            # ----------------------------------------------------------

            models.UniqueConstraint(
                fields=(
                    "payment",
                    "attempt_number",
                ),
                name="payment_attempt_payment_number_uniq",
            ),

            models.CheckConstraint(
                condition=Q(attempt_number__gte=1),
                name="payment_attempt_number_positive",
            ),

            # ----------------------------------------------------------
            # Retry invariants
            # ----------------------------------------------------------

            models.CheckConstraint(
                condition=Q(retry_count__gte=0),
                name="payment_attempt_retry_non_negative",
            ),

            # ----------------------------------------------------------
            # State / timestamp invariants
            # ----------------------------------------------------------

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

            models.CheckConstraint(
                condition=(
                    Q(finished_at__isnull=True)
                    |
                    Q(
                        finished_at__gte=F("started_at"),
                    )
                ),
                name="payment_attempt_finish_after_start",
            ),
        ]

        indexes = [
            # Latest attempts for a payment.
            models.Index(
                fields=(
                    "payment",
                    "status",
                    "-attempt_number",
                ),
                name="pay_attempt_payment_status_idx",
            ),

            # Operational monitoring / background workers.
            models.Index(
                fields=(
                    "status",
                    "-started_at",
                ),
                name="pay_attempt_status_started_idx",
            ),

            # Payment-scoped identity lookups.
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

            # Callback/reconciliation workers.
            models.Index(
                fields=(
                    "callback_received_at",
                    "status",
                ),
                name="pay_attempt_callback_status_idx",
            ),
        ]

    # ============================
    # Validation
    # ============================

    def clean(self) -> None:
        """
        Validate entity invariants.

        This method is side-effect free.

        Important:
            Django does not automatically execute clean() from save().
            Database constraints and application-level validation remain
            necessary.
        """
        super().clean()

        self._validate_state()
        self._validate_identity()
        self._validate_retry()
        self._validate_dates()
        self._validate_latency()
        self._validate_retry_relationship()

    # ============================
    # State Properties
    # ============================

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
        return self.status in self.TERMINAL_STATUSES

    @property
    def is_finished(self) -> bool:
        return (
            self.is_terminal
            and self.finished_at is not None
        )

    # ============================
    # Gateway Identity
    # ============================

    @property
    def external_reference(self) -> str | None:
        """
        Return the strongest available external identifier.

        Priority:

            gateway_transaction_id
                ↓
            gateway_reference
                ↓
            authority_id

        This property is intended for domain/application usage.

        Repository queries must NOT depend on this property.
        Each gateway identity must be queried explicitly.
        """
        return (
            self.gateway_transaction_id
            or self.gateway_reference
            or self.authority_id
            or None
        )

    # ============================
    # Domain Commands
    # ============================

    def mark_success(
        self,
        *,
        authority_id: str = "",
        gateway_reference: str = "",
        gateway_transaction_id: str = "",
        response_code: str = "",
        gateway_message: str = "",
        latency_ms: int | None = None,
    ) -> PaymentAttempt:
        """
        Transition PENDING -> SUCCESS.

        If the attempt is already SUCCESS, this operation becomes
        idempotent reconciliation.

        No database query, transaction or save() is performed here.
        """

        if self.is_success:
            return self._reconcile_success(
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

        self._set_authority(authority_id)
        self._set_reference(gateway_reference)
        self._set_transaction(gateway_transaction_id)

        self._set_gateway_metadata(
            response_code=response_code,
            gateway_message=gateway_message,
        )

        self.failure_reason = ""

        self._finish(
            status=PaymentAttemptStatus.SUCCESS,
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
    ) -> PaymentAttempt:
        """
        Transition PENDING -> FAILED.
        """
        return self._mark_terminal(
            status=PaymentAttemptStatus.FAILED,
            reason=reason,
            response_code=response_code,
            gateway_message=gateway_message,
            latency_ms=latency_ms,
        )

    def mark_timeout(
        self,
        *,
        reason: str = "",
        latency_ms: int | None = None,
    ) -> PaymentAttempt:
        """
        Transition PENDING -> TIMEOUT.
        """
        return self._mark_terminal(
            status=PaymentAttemptStatus.TIMEOUT,
            reason=reason,
            latency_ms=latency_ms,
        )

    def mark_cancelled(
        self,
        *,
        reason: str = "",
    ) -> PaymentAttempt:
        """
        Transition PENDING -> CANCELLED.
        """
        return self._mark_terminal(
            status=PaymentAttemptStatus.CANCELLED,
            reason=reason,
        )

    # ============================
    # Callback
    # ============================

    def register_callback(
        self,
        *,
        received_at=None,
    ) -> PaymentAttempt:
        """
        Register that a gateway callback was received.

        This does not imply SUCCESS.

        Callback processing and reconciliation belong to the
        application/service layer.
        """

        if received_at is None:
            received_at = timezone.now()

        self._require(
            received_at is not None,
            _("Callback timestamp is required."),
        )

        self.callback_received_at = received_at

        return self

    # ============================
    # Gateway Response
    # ============================

    def register_gateway_response(
        self,
        *,
        response_code: str = "",
        gateway_message: str = "",
    ) -> PaymentAttempt:
        """
        Register normalized gateway response metadata.

        Raw gateway request/response payloads belong to GatewayLog.
        """

        self._require(
            self.is_pending,
            _(
                "Gateway response can only be registered "
                "for a pending attempt."
            ),
        )

        self._set_gateway_metadata(
            response_code=response_code,
            gateway_message=gateway_message,
        )

        return self

    # ============================
    # Latency
    # ============================

    def record_latency(
        self,
        *,
        latency_ms: int,
    ) -> PaymentAttempt:
        """
        Record an explicit latency measurement.
        """

        self._validate_latency_value(latency_ms)

        self.latency_ms = latency_ms

        return self

    # ============================
    # Internal State Transition
    # ============================

    def _mark_terminal(
        self,
        *,
        status: PaymentAttemptStatus,
        reason: str = "",
        response_code: str = "",
        gateway_message: str = "",
        latency_ms: int | None = None,
    ) -> PaymentAttempt:
        """
        Transition the attempt into a terminal state.
        """

        self._require_transition(status)

        self._set_gateway_metadata(
            response_code=response_code,
            gateway_message=gateway_message,
        )

        self.failure_reason = self._normalize(reason)

        self._finish(
            status=status,
            latency_ms=latency_ms,
        )

        return self

    def _finish(
        self,
        *,
        status: PaymentAttemptStatus,
        latency_ms: int | None = None,
    ) -> None:
        """
        Complete a valid state transition.

        Transition must already have been validated by the caller.
        """

        finished_at = timezone.now()

        self.status = status
        self.finished_at = finished_at

        self.latency_ms = self._resolve_latency(
            latency_ms=latency_ms,
            finished_at=finished_at,
        )

    # ============================
    # SUCCESS Reconciliation
    # ============================

    def _reconcile_success(
        self,
        *,
        authority_id: str,
        gateway_reference: str,
        gateway_transaction_id: str,
        response_code: str,
        gateway_message: str,
        latency_ms: int | None,
    ) -> PaymentAttempt:
        """
        Reconcile duplicate SUCCESS notifications.

        Existing gateway identities are immutable.

        Missing identities may be completed later.

        Conflicting identities are rejected.
        """

        self._set_authority(authority_id)
        self._set_reference(gateway_reference)
        self._set_transaction(gateway_transaction_id)

        self._set_gateway_metadata(
            response_code=response_code,
            gateway_message=gateway_message,
        )

        if self.latency_ms is None and latency_ms is not None:
            self._validate_latency_value(latency_ms)
            self.latency_ms = latency_ms

        self.failure_reason = ""

        return self

    # ============================
    # Gateway Identity Assignment
    # ============================

    def _set_authority(
        self,
        authority_id: str,
    ) -> None:
        """
        Assign authority identifier once.

        Empty incoming values are ignored.
        """

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

    def _set_reference(
        self,
        gateway_reference: str,
    ) -> None:
        """
        Assign gateway reference once.

        Empty incoming values are ignored.
        """

        gateway_reference = self._normalize(
            gateway_reference,
        )

        if not gateway_reference:
            return

        if not self.gateway_reference:
            self.gateway_reference = gateway_reference
            return

        self._require(
            self.gateway_reference == gateway_reference,
            _("Gateway reference conflict detected."),
        )

    def _set_transaction(
        self,
        gateway_transaction_id: str,
    ) -> None:
        """
        Assign gateway transaction identifier once.

        Empty incoming values are ignored.
        """

        gateway_transaction_id = self._normalize(
            gateway_transaction_id,
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

    # ============================
    # Gateway Metadata
    # ============================

    def _set_gateway_metadata(
        self,
        *,
        response_code: str = "",
        gateway_message: str = "",
    ) -> None:
        """
        Update normalized gateway metadata.

        Empty values do not erase existing metadata.
        """

        response_code = self._normalize(response_code)
        gateway_message = self._normalize(gateway_message)

        if response_code:
            self.response_code = response_code

        if gateway_message:
            self.gateway_message = gateway_message

    # ============================
    # Validation
    # ============================

    def _validate_state(self) -> None:
        """
        Validate status/timestamp relationship.
        """

        if self.is_pending:
            self._require(
                self.finished_at is None,
                _(
                    "Pending attempts cannot have "
                    "a finished timestamp."
                ),
            )
            return

        self._require(
            self.status in self.TERMINAL_STATUSES,
            _("Unknown terminal payment attempt status."),
        )

        self._require(
            self.finished_at is not None,
            _(
                "Terminal attempts require "
                "a finished timestamp."
            ),
        )

    def _validate_identity(self) -> None:
        """
        Validate gateway identity invariants.

        Gateway identity is intentionally not tied to SUCCESS.

        Different gateways may expose authority/reference/transaction
        identifiers at different stages of their lifecycle.
        """

        if self.is_success and self.failure_reason:
            raise ValidationError(
                {
                    "failure_reason": _(
                        "Successful attempts cannot contain "
                        "a failure reason."
                    )
                }
            )

    def _validate_retry(self) -> None:
        """
        Validate retry counters.
        """

        if self.attempt_number < 1:
            raise ValidationError(
                {
                    "attempt_number": _(
                        "Attempt number must be greater than zero."
                    )
                }
            )

        if self.retry_count < 0:
            raise ValidationError(
                {
                    "retry_count": _(
                        "Retry count cannot be negative."
                    )
                }
            )

    def _validate_retry_relationship(self) -> None:
        """
        Validate the local retry relationship.

        Cross-row consistency should additionally be validated by
        the application/repository creation workflow.
        """

        if self.retry_of is None:
            if self.retry_count != 0:
                raise ValidationError(
                    {
                        "retry_count": _(
                            "An initial attempt must have "
                            "retry_count=0."
                        )
                    }
                )
            return

        if self.pk and self.retry_of.pk == self.pk:
            raise ValidationError(
                {
                    "retry_of": _(
                        "An attempt cannot retry itself."
                    )
                }
            )

        if (
            self.payment_id is not None
            and self.retry_of.payment_id is not None
            and self.payment_id != self.retry_of.payment_id
        ):
            raise ValidationError(
                {
                    "retry_of": _(
                        "Retry attempt must belong to "
                        "the same payment aggregate."
                    )
                }
            )

        if (
            self.retry_of.attempt_number
            >= self.attempt_number
        ):
            raise ValidationError(
                {
                    "retry_of": _(
                        "A retry must reference an earlier attempt."
                    )
                }
            )

        expected_retry_count = self.retry_of.retry_count + 1

        if self.retry_count != expected_retry_count:
            raise ValidationError(
                {
                    "retry_count": _(
                        "Retry count must equal the previous "
                        "attempt retry count plus one."
                    )
                }
            )

    def _validate_dates(self) -> None:
        """
        Validate temporal ordering.
        """

        if (
            self.started_at is not None
            and self.finished_at is not None
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

        if (
            self.callback_received_at is not None
            and self.started_at is not None
            and self.callback_received_at < self.started_at
        ):
            raise ValidationError(
                {
                    "callback_received_at": _(
                        "Callback received time cannot be "
                        "earlier than attempt start time."
                    )
                }
            )

    def _validate_latency(self) -> None:
        """
        Validate latency.
        """

        if self.latency_ms is not None:
            self._validate_latency_value(
                self.latency_ms,
            )

    @staticmethod
    def _validate_latency_value(
        latency_ms: int,
    ) -> None:
        if latency_ms < 0:
            raise ValidationError(
                _("Latency cannot be negative.")
            )

    # ============================
    # Latency Helpers
    # ============================

    def _calculate_latency(
        self,
        *,
        finished_at,
    ) -> int | None:
        """
        Calculate latency from start and finish timestamps.
        """

        if (
            self.started_at is None
            or finished_at is None
        ):
            return None

        elapsed = finished_at - self.started_at

        return max(
            0,
            int(elapsed.total_seconds() * 1000),
        )

    def _resolve_latency(
        self,
        *,
        latency_ms: int | None,
        finished_at,
    ) -> int | None:
        """
        Prefer explicit gateway latency.

        Otherwise calculate latency from timestamps.
        """

        if latency_ms is not None:
            self._validate_latency_value(
                latency_ms,
            )
            return latency_ms

        return self._calculate_latency(
            finished_at=finished_at,
        )

    # ============================
    # Transition Guards
    # ============================

    def _require_transition(
        self,
        target: PaymentAttemptStatus,
    ) -> None:
        """
        Ensure the requested state transition is valid.
        """

        allowed = self.ALLOWED_TRANSITIONS.get(
            self.status,
            frozenset(),
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

    # ============================
    # Generic Guards
    # ============================

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

    # ============================
    # Representation
    # ============================

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