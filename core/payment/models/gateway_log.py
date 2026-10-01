# core/payment/models/gateway_log.py

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from payment.enums import (
    GatewayLogDirection,
    GatewayLogType,
    PaymentGateway,
)
from payment.managers import GatewayLogManager


class GatewayLog(models.Model):
    """
    Immutable Gateway Communication Audit Entity.

    GatewayLog represents exactly one technical communication
    between the application and an external payment gateway.

    Ownership invariant
    -------------------
    Every GatewayLog MUST belong to exactly one financial operation:

        PaymentAttempt XOR Refund

    Therefore:

        attempt != NULL AND refund == NULL
        OR
        attempt == NULL AND refund != NULL

    The following states are forbidden:

        attempt == NULL AND refund == NULL
        attempt != NULL AND refund != NULL

    GatewayLog is an immutable append-only audit record.

    Responsibilities
    ----------------
    - Audit gateway communication.
    - Store sanitized transport evidence.
    - Store normalized gateway results.
    - Store technical exceptions.
    - Store request context.
    - Preserve historical gateway evidence.

    Explicitly NOT responsible for
    --------------------------------
    - Payment state transitions.
    - PaymentAttempt state transitions.
    - Refund state transitions.
    - Gateway execution.
    - HTTP requests.
    - Business rules.
    - Repository operations.
    - Transaction orchestration.
    - Reconciliation decisions.
    - Event publication.

    Financial aggregate ownership remains outside this model.
    """

    # ================================
    # Ownership
    # ================================

    attempt = models.ForeignKey(
        "payment.PaymentAttempt",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="gateway_logs",
        help_text=_(
            "Payment attempt associated with this gateway communication."
        ),
    )

    refund = models.ForeignKey(
        "payment.Refund",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="gateway_logs",
        help_text=_(
            "Refund associated with this gateway communication."
        ),
    )

    # ================================
    # Gateway Context
    # ================================

    gateway = models.CharField(
        max_length=32,
        choices=PaymentGateway.choices,
        db_index=True,
        help_text=_(
            "Payment gateway involved in this communication."
        ),
    )

    log_type = models.CharField(
        max_length=32,
        choices=GatewayLogType.choices,
        db_index=True,
        help_text=_(
            "Type of gateway communication."
        ),
    )

    direction = models.CharField(
        max_length=16,
        choices=GatewayLogDirection.choices,
        db_index=True,
        help_text=_(
            "Direction of communication between application and gateway."
        ),
    )

    # ================================
    # HTTP Metadata
    # ================================

    request_url = models.URLField(
        max_length=2048,
        blank=True,
        default="",
        help_text=_(
            "Gateway endpoint URL used for this request."
        ),
    )

    request_method = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text=_(
            "HTTP method used for the request."
        ),
    )

    http_status = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=_(
            "HTTP status code returned by the gateway."
        ),
    )

    latency_ms = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=_(
            "Measured request latency in milliseconds."
        ),
    )

    # ================================
    # Raw / Sanitized Transport Data
    # ================================
    #
    # IMPORTANT:
    # These fields are audit evidence.
    #
    # They MUST be sanitized before entering this model.
    #
    # The model itself must not attempt to sanitize secrets.
    # ================================

    request_headers = models.JSONField(
        default=dict,
        blank=True,
        encoder=DjangoJSONEncoder,
        help_text=_(
            "Sanitized HTTP request headers sent to the gateway."
        ),
    )

    request_payload = models.JSONField(
        default=dict,
        blank=True,
        encoder=DjangoJSONEncoder,
        help_text=_(
            "Sanitized request payload sent to the gateway."
        ),
    )

    response_headers = models.JSONField(
        default=dict,
        blank=True,
        encoder=DjangoJSONEncoder,
        help_text=_(
            "Sanitized HTTP response headers returned by the gateway."
        ),
    )

    response_payload = models.JSONField(
        default=dict,
        blank=True,
        encoder=DjangoJSONEncoder,
        help_text=_(
            "Sanitized response payload returned by the gateway."
        ),
    )

    # ================================
    # Normalized Gateway Result
    # ================================

    response_code = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_index=True,
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

    is_success = models.BooleanField(
        null=True,
        blank=True,
        db_index=True,
        help_text=_(
            "Normalized gateway communication result."
        ),
    )

    exception = models.TextField(
        blank=True,
        default="",
        help_text=_(
            "Captured technical exception information."
        ),
    )

    # ================================
    # Client Metadata
    # ================================

    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text=_(
            "Client IP address associated with this gateway communication."
        ),
    )

    user_agent = models.TextField(
        blank=True,
        default="",
        help_text=_(
            "Client user-agent associated with this gateway communication."
        ),
    )

    meta = models.JSONField(
        default=dict,
        blank=True,
        encoder=DjangoJSONEncoder,
        help_text=_(
            "Additional non-sensitive structured audit metadata."
        ),
    )

    # ================================
    # Timestamp
    # ================================

    created_date = models.DateTimeField(
        auto_now_add=True,
        editable=False,
        db_index=True,
        help_text=_(
            "Timestamp when this audit record was created."
        ),
    )

    # ================================
    # Manager
    # ================================

    objects = GatewayLogManager()

    # ================================
    # Meta
    # ================================

    class Meta:
        verbose_name = _("Gateway Log")
        verbose_name_plural = _("Gateway Logs")

        ordering = (
            "-created_date",
            "-id",
        )

        constraints = [

            # ================================
            # CRITICAL OWNERSHIP INVARIANT
            # ================================
            #
            # Exactly one owner:
            #     attempt XOR refund
            #
            # Allowed:
            #     attempt != NULL
            #     refund  == NULL
            #
            # OR
            #
            #     attempt == NULL
            #     refund  != NULL
            #
            # Forbidden:
            #     both NULL
            #     both NOT NULL
            #
            # This is deliberately enforced at the DATABASE level.
            # ================================

            models.CheckConstraint(
                condition=(
                    Q(
                        attempt__isnull=False,
                        refund__isnull=True,
                    )
                    |
                    Q(
                        attempt__isnull=True,
                        refund__isnull=False,
                    )
                ),
                name="gateway_log_exactly_one_owner",
            ),

            # ================================
            # HTTP STATUS
            # ================================

            models.CheckConstraint(
                condition=(
                    Q(http_status__isnull=True)
                    |
                    Q(
                        http_status__gte=100,
                        http_status__lte=599,
                    )
                ),
                name="gateway_log_http_status_valid",
            ),

            # ================================
            # LATENCY
            # ================================

            models.CheckConstraint(
                condition=Q(latency_ms__isnull=True)
                | Q(latency_ms__gte=0),
                name="gateway_log_latency_non_negative",
            ),
        ]

        indexes = [

            models.Index(
                fields=(
                    "attempt",
                    "-created_date",
                ),
                name="gw_log_attempt_created_idx",
            ),

            models.Index(
                fields=(
                    "refund",
                    "-created_date",
                ),
                name="gw_log_refund_created_idx",
            ),

            models.Index(
                fields=(
                    "gateway",
                    "log_type",
                    "-created_date",
                ),
                name="gw_log_gateway_type_idx",
            ),

            models.Index(
                fields=(
                    "gateway",
                    "is_success",
                    "-created_date",
                ),
                name="gw_log_gateway_success_idx",
            ),
        ]

    # ================================
    # Validation
    # ================================

    def clean(self) -> None:
        """
        Validate GatewayLog invariants.

        Database constraints remain the final integrity barrier.

        This method exists for:
            - developer feedback,
            - service-layer validation,
            - admin/forms,
            - deterministic model validation.

        It is NOT considered a replacement for DB constraints.
        """

        super().clean()

        # ------------------------------------------------------
        # Exactly one owner
        # ------------------------------------------------------

        has_attempt = self.attempt_id is not None
        has_refund = self.refund_id is not None

        if has_attempt == has_refund:
            raise ValidationError(
                _(
                    "Gateway log must belong to exactly one "
                    "payment attempt or refund."
                )
            )

        # ------------------------------------------------------
        # HTTP status
        # ------------------------------------------------------

        if (
            self.http_status is not None
            and not 100 <= self.http_status <= 599
        ):
            raise ValidationError(
                {
                    "http_status": _(
                        "HTTP status code must be between "
                        "100 and 599."
                    )
                }
            )

        # ------------------------------------------------------
        # Latency
        # ------------------------------------------------------

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

        # ------------------------------------------------------
        # HTTP method normalization
        # ------------------------------------------------------

        if self.request_method:

            normalized_method = (
                self.request_method.strip().upper()
            )

            if normalized_method != self.request_method:
                raise ValidationError(
                    {
                        "request_method": _(
                            "HTTP method must be normalized "
                            "to uppercase without surrounding "
                            "whitespace."
                        )
                    }
                )

            if " " in normalized_method:
                raise ValidationError(
                    {
                        "request_method": _(
                            "HTTP method cannot contain whitespace."
                        )
                    }
                )

    # ================================
    # Persistence
    # ================================

    def save(self, *args, **kwargs):
        """
        Persist the audit entity.

        GatewayLog is immutable.

        Once persisted:
            - no update
            - no overwrite
            - no mutation through save()

        Every new gateway communication must create
        a new GatewayLog record.
        """

        if self.pk is not None:
            raise ValidationError(
                _(
                    "GatewayLog is immutable and cannot be updated."
                )
            )

        self.full_clean()

        return super().save(
            *args,
            **kwargs,
        )

    # ================================
    # Deletion Protection
    # ================================

    def delete(self, *args, **kwargs):
        """
        GatewayLog records are historical audit evidence.

        They must not be deleted through the domain model.
        """

        raise ValidationError(
            _(
                "GatewayLog is immutable and cannot be deleted."
            )
        )

    # ================================
    # Representation
    # ================================

    def __str__(self) -> str:

        owner = (
            f"attempt={self.attempt_id}"
            if self.attempt_id is not None
            else f"refund={self.refund_id}"
        )

        return (
            f"GatewayLog<"
            f"{owner}, "
            f"gateway={self.gateway}, "
            f"type={self.log_type}, "
            f"direction={self.direction}"
            f">"
        )