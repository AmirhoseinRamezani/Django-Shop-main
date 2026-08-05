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
            │
            ├── Attempt #2 -> failed
            │
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

    # Identity
    # =======================
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

    # =======================
    # Gateway References
    # =======================
    #
    # These fields contain gateway-generated identifiers only.
    #
    # Raw request/response payloads MUST NOT be stored here.
    # They belong to GatewayLog.
    #
    # After a successful attempt, gateway identifiers become immutable
    # from a domain perspective.
    # =======================

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
    
    # In case you want to have a Retry Chain later ..
    # =======================
    retry_of = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="retries",
    )

    # State
    # =======================
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

    # Timing
    # =======================
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

    # Request Context
    # =======================
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

    # Metadata
    # =======================
    meta = models.JSONField(
        default=dict,
        blank=True,
        encoder=DjangoJSONEncoder,
        help_text=_(
            "Non-sensitive structured metadata associated with this attempt."
        ),
    )

    # =======================
    # Manager
    # =======================

    objects = PaymentAttemptManager()

    # =======================
    # Meta
    # =======================

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

            # -----------------------------------------------
            # Attempt number must always be positive.
            # -----------------------------------------------
            models.CheckConstraint(
                condition=Q(attempt_number__gte=1),
                name="payment_attempt_number_positive",
            ),

            # -----------------------------------------------
            # A successful attempt must have a reference ID.
            # -----------------------------------------------
            models.CheckConstraint(
                condition=(
                    ~Q(status=PaymentAttemptStatus.SUCCESS)
                    | 
                    Q(gateway_reference__gt="")
                ),
                name="payment_attempt_success_requires_ref",
            ),

            # -----------------------------------------------
            # Terminal attempts must have a completion timestamp.
            #
            # PENDING is the only non-terminal state.
            # -----------------------------------------------
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

            # -----------------------------------------------
            # finished_at can never be earlier than started_at.
            # -----------------------------------------------
            models.CheckConstraint(
                condition=(
                    Q(finished_at__isnull=True)
                    | 
                    Q(finished_at__gte=models.F("started_at"))
                ),
                name="payment_attempt_finish_after_start",
            ),

            # -----------------------------------------------
            # Latency cannot be negative.
            #
            # PositiveIntegerField already protects this at DB level on
            # supported backends, but the semantic constraint is explicit.
            # -----------------------------------------------
            models.CheckConstraint(
                condition=(
                    Q(latency_ms__isnull=True)
                    | 
                    Q(latency_ms__gte=0)
                ),
                name="payment_attempt_latency_non_negative",
            ),
        ]

        indexes = [
            # -----------------------------------------------
            # Main query:
            #
            # payment.attempts ordered by newest attempt first.
            #
            # Note:
            # UniqueConstraint(payment, attempt_number) already creates a
            # unique index. This index is intentionally kept because the
            # ordering direction is different and represents a hot read path.
            # -----------------------------------------------
            models.Index(
                fields=[
                    "payment",
                    "-attempt_number",
                ],
                name="pay_attempt_payment_num_idx",
            ),

            # -----------------------------------------------
            # Find the latest pending attempt for a payment.
            # -----------------------------------------------
            models.Index(
                fields=[
                    "payment",
                    "status",
                    "-attempt_number",
                ],
                name="pay_attempt_payment_status_idx",
            ),

            # -----------------------------------------------
            # Operational monitoring:
            #
            # Find recent attempts by status.
            # -----------------------------------------------
            models.Index(
                fields=[
                    "status",
                    "-started_at",
                ],
                name="pay_attempt_status_started_idx",
            ),

            # -----------------------------------------------
            # Gateway reconciliation / callback lookup.
            # -----------------------------------------------
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

            # -----------------------------------------------
            # Gateway authority lookup.
            # -----------------------------------------------
            models.Index(
                fields=[
                    "authority_id",
                    "status",
                ],
                name="pay_attempt_authority_status_idx",
            ),
        ]

    # =======================
    # Validation
    # =======================
    def clean(self) -> None:
        """
        Validate domain invariants.

        This method is intentionally side-effect free.

        It:
            - Does not query the database.
            - Does not save the model.
            - Does not perform network operations.
            - Does not mutate the model.
        """

        super().clean()

        if self.attempt_number < 1:
            raise ValidationError(
                {
                    "attempt_number": _(
                        "Attempt number must be greater than zero."
                    )
                }
            )

        if (
            self.finished_at is not None
            and self.started_at is not None
            and self.finished_at < self.started_at
        ):
            raise ValidationError(
                {
                    "finished_at": _(
                        "Finished time cannot be earlier than "
                        "started time."
                    )
                }
            )

        if (
            self.status == PaymentAttemptStatus.SUCCESS
            and not self.gateway_reference
        ):
            raise ValidationError(
                {
                    "gateway_reference": _(
                        "A successful payment attempt requires "
                        "a gateway reference ID."
                    )
                }
            )

        if (
            self.status != PaymentAttemptStatus.PENDING
            and self.finished_at is None
        ):
            raise ValidationError(
                {
                    "finished_at": _(
                        "A completed payment attempt requires "
                        "a finished timestamp."
                    )
                }
            )

    # =======================
    # Persistence
    # =======================
    def save(self, *args, **kwargs):
        """
        Persist the entity.

        Domain methods intentionally do NOT call save().

        The application/repository layer decides:

            - when to persist;
            - which fields to update;
            - whether optimistic locking is required;
            - whether a transaction is required.

        Model validation is performed before persistence.
        """

        self.full_clean()

        return super().save(
            *args,
            **kwargs,
        )

    # =======================
    # State Properties
    # =======================
    @property
    def is_pending(self) -> bool:
        """Return True when the attempt is still in progress."""

        return self.status == PaymentAttemptStatus.PENDING

    @property
    def is_success(self) -> bool:
        """Return True when the gateway attempt succeeded."""

        return self.status == PaymentAttemptStatus.SUCCESS

    @property
    def is_failed(self) -> bool:
        """Return True when the gateway attempt failed."""

        return self.status == PaymentAttemptStatus.FAILED

    @property
    def is_timeout(self) -> bool:
        """Return True when the gateway communication timed out."""

        return self.status == PaymentAttemptStatus.TIMEOUT

    @property
    def is_cancelled(self) -> bool:
        """Return True when the attempt was cancelled."""

        return self.status == PaymentAttemptStatus.CANCELLED

    @property
    def is_finished(self) -> bool:
        """
        Return True when the attempt reached a terminal state.
        """

        return (
            self.status != PaymentAttemptStatus.PENDING
            and self.finished_at is not None
        )

    @property
    def gateway_reference(self) -> Optional[str]:
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

    # =======================
    # Domain: Success
    # =======================
    def mark_success(
        self,
        *,
        gateway_reference: str,
        gateway_transaction_id: str = "",
        response_code: str = "",
        gateway_message: str = "",
        latency_ms: Optional[int] = None,
    ) -> "PaymentAttempt":
        """
        Mark the attempt as successful.

        Important:
            This method is side-effect free with respect to persistence.

        It only mutates the in-memory domain entity.

        The caller must persist the resulting state through the
        repository/application layer.

        Idempotency:
            Calling this method again with the same gateway references
            is allowed.

        Immutability:
            Once SUCCESS, gateway identifiers cannot be changed.
        """

        normalized_ref_id = str(
            gateway_reference or ""
        ).strip()

        normalized_transaction_id = str(
            gateway_transaction_id or ""
        ).strip()

        normalized_response_code = str(
            response_code or ""
        ).strip()

        normalized_gateway_message = str(
            gateway_message or ""
        ).strip()

        if not normalized_ref_id:
            raise ValidationError(
                _(
                    "A successful payment attempt requires "
                    "a reference ID."
                )
            )

        if latency_ms is not None and latency_ms < 0:
            raise ValidationError(
                _(
                    "Latency cannot be negative."
                )
            )

        # -----------------------------------------------
        # Idempotent success.
        #
        # A successful attempt may receive the same success notification
        # more than once due to retries or duplicate callbacks.
        # -----------------------------------------------
        if self.is_success:

            if self.gateway_reference != normalized_ref_id:
                raise ValidationError(
                    _(
                        "Reference ID cannot be changed after "
                        "successful payment."
                    )
                )

            if (
                self.gateway_transaction_id
                and normalized_transaction_id
                and (
                    self.gateway_transaction_id
                    != normalized_transaction_id
                )
            ):
                raise ValidationError(
                    _(
                        "Gateway transaction ID cannot be changed "
                        "after successful payment."
                    )
                )

            # An identifier that was previously unavailable may be enriched
            # by a later callback, but an existing identifier is immutable.
            if (
                not self.gateway_transaction_id
                and normalized_transaction_id
            ):
                self.gateway_transaction_id = (
                    normalized_transaction_id
                )

            if normalized_response_code:
                self.response_code = normalized_response_code

            if normalized_gateway_message:
                self.gateway_message = normalized_gateway_message

            if latency_ms is not None:
                self.latency_ms = latency_ms

            return self

        # -----------------------------------------------
        # Terminal attempts cannot transition to SUCCESS.
        # -----------------------------------------------
        if self.is_finished:
            raise ValidationError(
                _(
                    "A finished payment attempt cannot be marked "
                    "as successful."
                )
            )

        now = timezone.now()

        self.status = PaymentAttemptStatus.SUCCESS

        self.gateway_reference = normalized_ref_id

        self.gateway_transaction_id = (
            normalized_transaction_id
        )

        self.response_code = normalized_response_code

        self.gateway_message = normalized_gateway_message

        self.failure_reason = ""

        self.finished_at = now

        self.latency_ms = (
            latency_ms
            if latency_ms is not None
            else self._calculate_latency_ms(
                finished_at=now,
            )
        )

        return self

    # =======================
    # Domain: Failure
    # =======================
    def mark_failed(
        self,
        *,
        reason: str = "",
        response_code: str = "",
        gateway_message: str = "",
        latency_ms: Optional[int] = None,
    ) -> "PaymentAttempt":
        """
        Mark the attempt as failed.

        This method does not persist the entity.

        A successful attempt cannot transition back to FAILED.
        """

        if self.is_success:
            raise ValidationError(
                _(
                    "A successful payment attempt cannot fail."
                )
            )

        if self.is_finished:
            return self

        if latency_ms is not None and latency_ms < 0:
            raise ValidationError(
                _(
                    "Latency cannot be negative."
                )
            )

        now = timezone.now()

        self.status = PaymentAttemptStatus.FAILED

        self.failure_reason = str(
            reason or ""
        ).strip()

        self.response_code = str(
            response_code or ""
        ).strip()

        self.gateway_message = str(
            gateway_message or ""
        ).strip()

        self.finished_at = now

        self.latency_ms = (
            latency_ms
            if latency_ms is not None
            else self._calculate_latency_ms(
                finished_at=now,
            )
        )

        return self

    # =======================
    # Domain: Timeout
    # =======================
    def mark_timeout(
        self,
        *,
        reason: str = "",
        latency_ms: Optional[int] = None,
    ) -> "PaymentAttempt":
        """
        Mark the attempt as timed out.

        Timeout is a terminal state for this attempt.
        """

        if self.is_success:
            raise ValidationError(
                _(
                    "A successful payment attempt cannot timeout."
                )
            )

        if self.is_finished:
            return self

        if latency_ms is not None and latency_ms < 0:
            raise ValidationError(
                _(
                    "Latency cannot be negative."
                )
            )

        now = timezone.now()

        self.status = PaymentAttemptStatus.TIMEOUT

        self.failure_reason = str(
            reason or ""
        ).strip()

        self.finished_at = now

        self.latency_ms = (
            latency_ms
            if latency_ms is not None
            else self._calculate_latency_ms(
                finished_at=now,
            )
        )

        return self

    # =======================
    # Domain: Cancellation
    # =======================
    def mark_cancelled(
        self,
        *,
        reason: str = "",
    ) -> "PaymentAttempt":
        """
        Mark the attempt as cancelled.

        Cancellation is a terminal state.
        """

        if self.is_success:
            raise ValidationError(
                _(
                    "A successful payment attempt cannot be cancelled."
                )
            )

        if self.is_finished:
            return self

        now = timezone.now()

        self.status = PaymentAttemptStatus.CANCELLED

        self.failure_reason = str(
            reason or ""
        ).strip()

        self.finished_at = now

        self.latency_ms = (
            self._calculate_latency_ms(
                finished_at=now,
            )
        )

        return self

    # =======================
    # Domain Helpers
    # =======================
    def _calculate_latency_ms(
        self,
        *,
        finished_at,
    ) -> Optional[int]:
        """
        Calculate attempt latency from start and finish timestamps.

        This helper performs no persistence.
        """

        if (
            self.started_at is None
            or finished_at is None
        ):
            return None

        elapsed = (
            finished_at
            - self.started_at
        )

        return max(
            0,
            int(
                elapsed.total_seconds()
                * 1000
            ),
        )

    # =======================
    # Representation
    # =======================
    def __str__(self) -> str:
        return (
            f"PaymentAttempt<"
            f"payment={self.payment_id}, "
            f"number={self.attempt_number}, "
            f"status={self.status}"
            f">"
        )
