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
    """One independent refund lifecycle belonging to a successful Payment.

    Refund is a domain entity, not a workflow engine. It never performs
    gateway I/O, opens transactions, queries repositories, aggregates other
    refunds, mutates Payment/Order, dispatches events, or persists itself from
    domain commands.

    Cumulative refundable-balance checks belong to the application service and
    MUST execute while holding the canonical Payment lock.
    """

    payment = models.ForeignKey(
        PaymentModel,
        on_delete=models.PROTECT,
        related_name="refunds",
        help_text=_("Payment aggregate against which this refund is requested."),
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        help_text=_("Immutable amount requested for this refund operation."),
    )

    currency = models.CharField(
        max_length=8,
        help_text=_("Immutable currency snapshot of the Payment."),
    )

    idempotency_key = models.CharField(
        max_length=128,
        unique=True,
        db_index=True,
        help_text=_("Application-level idempotency identity for this refund."),
    )

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

    status = models.CharField(
        max_length=20,
        choices=RefundStatus.choices,
        default=RefundStatus.PENDING,
        db_index=True,
    )

    gateway_reference = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_index=True,
    )

    gateway_transaction_id = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_index=True,
    )

    response_code = models.CharField(
        max_length=64,
        blank=True,
        default="",
    )

    gateway_message = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )

    failure_reason = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )

    requested_at = models.DateTimeField(auto_now_add=True)

    finished_at = models.DateTimeField(
        null=True,
        blank=True,
    )

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

    class Meta:
        verbose_name = _("Refund")
        verbose_name_plural = _("Refunds")
        ordering = ("-requested_at", "-id")
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="refund_amount_positive",
            ),
            models.CheckConstraint(
                condition=Q(currency__gt=""),
                name="refund_currency_required",
            ),
            models.CheckConstraint(
                condition=Q(idempotency_key__gt=""),
                name="refund_idempotency_key_required",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(status=RefundStatus.SUCCESS)
                    | Q(gateway_reference__gt="")
                    | Q(gateway_transaction_id__gt="")
                ),
                name="refund_success_requires_gateway_identity",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(status=RefundStatus.SUCCESS)
                    | Q(failure_reason="")
                ),
                name="refund_success_no_failure_reason",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status=RefundStatus.PENDING, finished_at__isnull=True)
                    | Q(
                        status__in=(RefundStatus.SUCCESS, RefundStatus.FAILED),
                        finished_at__isnull=False,
                    )
                ),
                name="refund_finished_state_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(finished_at__isnull=True)
                    | Q(finished_at__gte=F("requested_at"))
                ),
                name="refund_finish_after_request",
            ),
            models.UniqueConstraint(
                fields=("payment", "gateway_reference"),
                condition=Q(gateway_reference__gt=""),
                name="refund_payment_gateway_ref_uniq",
            ),
            models.UniqueConstraint(
                fields=("payment", "gateway_transaction_id"),
                condition=Q(gateway_transaction_id__gt=""),
                name="refund_payment_gateway_tx_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=("payment", "status", "-requested_at"),
                name="refund_payment_status_idx",
            ),
            models.Index(
                fields=("status", "-requested_at"),
                name="refund_status_requested_idx",
            ),
            models.Index(
                fields=("payment", "-requested_at"),
                name="refund_payment_requested_idx",
            ),
            models.Index(
                fields=("payment", "gateway_reference"),
                name="refund_payment_ref_idx",
            ),
            models.Index(
                fields=("payment", "gateway_transaction_id"),
                name="refund_payment_tx_idx",
            ),
        ]

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

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
        return self.status in {RefundStatus.SUCCESS, RefundStatus.FAILED}

    @property
    def is_finished(self) -> bool:
        return self.is_terminal and self.finished_at is not None

    @property
    def external_reference(self) -> Optional[str]:
        return self.gateway_transaction_id or self.gateway_reference or None

    def is_full_payment_refund(self, *, payment_amount: Decimal) -> bool:
        """Whether this individual refund equals the original Payment amount.

        This does not establish that the Payment is fully refunded; other
        successful Refund aggregates must be considered by the service.
        """
        return self.amount == Decimal(str(payment_amount))

    def validate_against_payment(
        self,
        *,
        payment_amount: Decimal,
        payment_currency: str,
    ) -> None:
        """Validate this refund against an already-loaded Payment snapshot.

        This deliberately avoids dereferencing ``self.payment`` so callers
        can perform validation after acquiring the Payment row lock without
        introducing an implicit query.
        """
        errors: dict[str, object] = {}
        if self.amount > Decimal(str(payment_amount)):
            errors["amount"] = _(
                "Refund amount cannot exceed the original Payment amount."
            )
        if self.currency != self._normalize(payment_currency):
            errors["currency"] = _(
                "Refund currency must match the Payment currency."
            )
        if errors:
            raise ValidationError(errors)

    # ------------------------------------------------------------------
    # Domain transitions
    # ------------------------------------------------------------------

    def mark_success(
        self,
        *,
        gateway_reference: str = "",
        gateway_transaction_id: str = "",
        response_code: str = "",
        gateway_message: str = "",
        latency_ms: int | None = None,
    ) -> "Refund":
        """Move PENDING -> SUCCESS, or reconcile an existing SUCCESS."""
        if self.is_success:
            return self._merge_success(
                gateway_reference=gateway_reference,
                gateway_transaction_id=gateway_transaction_id,
                response_code=response_code,
                gateway_message=gateway_message,
                latency_ms=latency_ms,
            )

        self._require_transition(RefundStatus.SUCCESS)
        reference = self._normalize(gateway_reference)
        transaction = self._normalize(gateway_transaction_id)

        self._require(
            bool(reference or transaction),
            _("A successful refund requires at least one gateway identity."),
        )

        self._assign_reference(reference)
        self._assign_transaction(transaction)
        self._update_gateway_metadata(
            response_code=response_code,
            gateway_message=gateway_message,
        )
        self.failure_reason = ""
        self._finish(RefundStatus.SUCCESS, latency_ms=latency_ms)
        return self

    def _merge_success(
        self,
        *,
        gateway_reference: str,
        gateway_transaction_id: str,
        response_code: str,
        gateway_message: str,
        latency_ms: int | None,
    ) -> "Refund":
        self._assign_reference(self._normalize(gateway_reference))
        self._assign_transaction(self._normalize(gateway_transaction_id))
        self._update_gateway_metadata(
            response_code=response_code,
            gateway_message=gateway_message,
        )
        self._record_success_latency(latency_ms)
        self.failure_reason = ""
        return self

    def mark_failed(
        self,
        *,
        reason: str = "",
        response_code: str = "",
        gateway_message: str = "",
        latency_ms: int | None = None,
    ) -> "Refund":
        """Move PENDING -> FAILED; a failed Refund is never resurrected."""
        if self.is_failed:
            self._update_gateway_metadata(
                response_code=response_code,
                gateway_message=gateway_message,
            )
            if reason:
                self.failure_reason = self._normalize(reason)
            self._record_existing_terminal_latency(latency_ms)
            return self

        self._require_transition(RefundStatus.FAILED)
        self._update_gateway_metadata(
            response_code=response_code,
            gateway_message=gateway_message,
        )
        self.failure_reason = self._normalize(reason)
        self._finish(RefundStatus.FAILED, latency_ms=latency_ms)
        return self

    def register_gateway_response(
        self,
        *,
        response_code: str = "",
        gateway_message: str = "",
    ) -> "Refund":
        """Store normalized response metadata while the refund is pending."""
        self._require(
            self.is_pending,
            _("Gateway response can only be registered for a pending refund."),
        )
        self._update_gateway_metadata(
            response_code=response_code,
            gateway_message=gateway_message,
        )
        return self

    # ------------------------------------------------------------------
    # Latency
    # ------------------------------------------------------------------

    def record_latency(self, *, latency_ms: int | None = None) -> "Refund":
        if latency_ms is None:
            return self
        self._require(latency_ms >= 0, _("Latency cannot be negative."))
        self.latency_ms = latency_ms
        return self

    def _calculate_latency(self, *, finished_at) -> Optional[int]:
        if self.requested_at is None or finished_at is None:
            return None
        elapsed = finished_at - self.requested_at
        return max(0, int(elapsed.total_seconds() * 1000))

    def _record_latency(self, *, latency_ms: int | None, finished_at) -> None:
        if latency_ms is None:
            self.latency_ms = self._calculate_latency(finished_at=finished_at)
            return
        self._require(latency_ms >= 0, _("Latency cannot be negative."))
        self.latency_ms = latency_ms

    def _record_success_latency(self, latency_ms: int | None) -> None:
        if self.latency_ms is None:
            self._record_latency(latency_ms=latency_ms, finished_at=self.finished_at)

    def _record_existing_terminal_latency(self, latency_ms: int | None) -> None:
        if self.latency_ms is None:
            self._record_latency(latency_ms=latency_ms, finished_at=self.finished_at)

    # ------------------------------------------------------------------
    # Gateway identity / metadata
    # ------------------------------------------------------------------

    def _assign_reference(self, value: str) -> None:
        if not value:
            return
        if not self.gateway_reference:
            self.gateway_reference = value
            return
        self._require(
            self.gateway_reference == value,
            _("Gateway refund reference conflict detected."),
        )

    def _assign_transaction(self, value: str) -> None:
        if not value:
            return
        if not self.gateway_transaction_id:
            self.gateway_transaction_id = value
            return
        self._require(
            self.gateway_transaction_id == value,
            _("Gateway refund transaction identifier conflict detected."),
        )

    def _update_gateway_metadata(
        self,
        *,
        response_code: str = "",
        gateway_message: str = "",
    ) -> None:
        response_code = self._normalize(response_code)
        gateway_message = self._normalize(gateway_message)
        if response_code:
            self.response_code = response_code
        if gateway_message:
            self.gateway_message = gateway_message

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def clean(self) -> None:
        super().clean()
        self._validate_invariants()

    def _validate_invariants(self) -> None:
        errors: dict[str, object] = {}

        if self.amount is None or self.amount <= Decimal("0"):
            errors["amount"] = _("Refund amount must be greater than zero.")
        if not self._normalize(self.currency):
            errors["currency"] = _("Refund currency is required.")
        if not self._normalize(self.idempotency_key):
            errors["idempotency_key"] = _("Refund idempotency key is required.")

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
            errors["status"] = _("Invalid refund state.")

        if self.is_success:
            if not (self.gateway_reference or self.gateway_transaction_id):
                errors["gateway_reference"] = _(
                    "Successful refunds require at least one gateway identity."
                )
            if self.failure_reason:
                errors["failure_reason"] = _(
                    "Successful refunds cannot contain a failure reason."
                )

        if (
            self.finished_at is not None
            and self.requested_at is not None
            and self.finished_at < self.requested_at
        ):
            errors["finished_at"] = _(
                "Finished time cannot be earlier than refund request time."
            )

        if self.latency_ms is not None and self.latency_ms < 0:
            errors["latency_ms"] = _("Latency cannot be negative.")

        if errors:
            raise ValidationError(errors)

    # ------------------------------------------------------------------
    # Guards / transition engine
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(value: str | None) -> str:
        return (value or "").strip()

    def _require(self, condition: bool, message: str) -> None:
        if not condition:
            raise ValidationError(message)

    _ALLOWED_TRANSITIONS = {
        RefundStatus.PENDING: {
            RefundStatus.SUCCESS,
            RefundStatus.FAILED,
        },
        RefundStatus.SUCCESS: set(),
        RefundStatus.FAILED: set(),
    }

    def _require_transition(self, target: RefundStatus) -> None:
        if self.status == target:
            return
        allowed = self._ALLOWED_TRANSITIONS.get(self.status, set())
        self._require(
            target in allowed,
            _(
                "Transition from '%(current)s' to '%(target)s' is not allowed."
            )
            % {"current": self.status, "target": target},
        )

    def _finish(self, status: RefundStatus, *, latency_ms: int | None = None) -> None:
        self._require_transition(status)
        finished_at = timezone.now()
        self.status = status
        self.finished_at = finished_at
        self._record_latency(latency_ms=latency_ms, finished_at=finished_at)

    def __str__(self) -> str:
        return (
            f"Refund(id={self.pk}, payment={self.payment_id}, "
            f"amount={self.amount} {self.currency}, "
            f"status={self.get_status_display()})"
        )

    def __repr__(self) -> str:
        return (
            f"<Refund id={self.pk} payment={self.payment_id} "
            f"amount={self.amount} currency={self.currency!r} "
            f"status={self.status!r}>"
        )
