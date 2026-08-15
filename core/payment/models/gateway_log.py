# payment/models/gateway_log.py
from __future__ import annotations

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
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

    GatewayLog stores the complete technical audit trail of
    communication between the application and an external
    payment gateway.

    Responsibilities
    ----------------
    GatewayLog is responsible for:

        - Auditing gateway communication.
        - Storing raw request payloads.
        - Storing raw response payloads.
        - Storing HTTP transport metadata.
        - Storing normalized gateway results.
        - Storing technical exceptions.
        - Storing client metadata.

    Explicitly NOT responsible for
    ------------------------------
    GatewayLog must NOT:

        - Change Payment state.
        - Change PaymentAttempt state.
        - Change Refund state.
        - Execute gateway requests.
        - Execute HTTP requests.
        - Execute business rules.
        - Perform repository operations.
        - Implement application workflows.

    GatewayLog is an immutable audit record.

    Raw gateway payloads MUST exist only inside GatewayLog.

    Every request, callback, verification, webhook,
    refund request and refund response should create
    a new GatewayLog instance instead of updating an
    existing one.
    """

    # ==========================================================
    # Ownership
    # ==========================================================
    #
    # GatewayLog belongs to exactly one business operation.
    #
    # Current owners:
    #
    #     • PaymentAttempt
    #     • Refund
    #
    # Never directly to Payment.
    # ==========================================================

    attempt = models.ForeignKey(
        "payment.PaymentAttempt",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="gateway_logs",
        help_text=_(
            "Payment attempt associated with this "
            "gateway communication."
        ),
    )

    refund = models.ForeignKey(
        "payment.Refund",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="gateway_logs",
        help_text=_(
            "Refund associated with this gateway "
            "communication."
        ),
    )

    # ==========================================================
    # Gateway Context
    # ==========================================================
    #
    # Describes what happened,
    # not the payload itself.
    # ==========================================================

    gateway = models.CharField(
        max_length=32,
        choices=PaymentGateway.choices,
        db_index=True,
        help_text=_(
            "Payment gateway involved in this "
            "communication."
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
            "Direction of communication between "
            "application and gateway."
        ),
    )
        # ==========================================================
    # HTTP Metadata
    # ==========================================================
    #
    # Technical transport information.
    #
    # These fields describe how the gateway
    # communication was performed.
    #
    # They do NOT contain business data.
    # ==========================================================

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

    # ==========================================================
    # Raw Transport Data
    # ==========================================================
    #
    # Gateway payloads are intentionally stored
    # without normalization.
    #
    # They are forensic evidence and may be required
    # for reconciliation, dispute resolution,
    # incident investigation and debugging.
    #
    # These payloads MUST NOT be modified after
    # persistence.
    # ==========================================================

    request_headers = models.JSONField(
        default=dict,
        blank=True,
        encoder=DjangoJSONEncoder,
        help_text=_(
            "Raw HTTP request headers sent to the gateway."
        ),
    )

    request_payload = models.JSONField(
        default=dict,
        blank=True,
        encoder=DjangoJSONEncoder,
        help_text=_(
            "Raw request payload sent to the gateway."
        ),
    )

    response_headers = models.JSONField(
        default=dict,
        blank=True,
        encoder=DjangoJSONEncoder,
        help_text=_(
            "Raw HTTP response headers returned by the gateway."
        ),
    )

    response_payload = models.JSONField(
        default=dict,
        blank=True,
        encoder=DjangoJSONEncoder,
        help_text=_(
            "Raw response payload returned by the gateway."
        ),
    )
        # ==========================================================
    # Normalized Gateway Result
    # ==========================================================
    #
    # These fields contain normalized information extracted
    # from the raw gateway response.
    #
    # The original payload always remains unchanged inside
    # request_payload / response_payload.
    #
    # These fields exist only to simplify querying,
    # monitoring and reconciliation.
    # ==========================================================

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

    # ==========================================================
    # Client Metadata
    # ==========================================================
    #
    # Request context useful for auditing.
    #
    # These values are optional because many gateway
    # communications are initiated internally
    # (verification workers, reconciliation jobs,
    # webhook processing, scheduled tasks, etc.).
    # ==========================================================

    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text=_(
            "Client IP address associated with this "
            "gateway communication."
        ),
    )

    user_agent = models.TextField(
        blank=True,
        default="",
        help_text=_(
            "Client user-agent associated with this "
            "gateway communication."
        ),
    )

    meta = models.JSONField(
        default=dict,
        blank=True,
        encoder=DjangoJSONEncoder,
        help_text=_(
            "Additional non-sensitive structured "
            "audit metadata."
        ),
    )

    # ==========================================================
    # Timestamp
    # ==========================================================

    created_date = models.DateTimeField(
        auto_now_add=True,
        editable=False,
        db_index=True,
        help_text=_(
            "Timestamp when this audit record was created."
        ),
    )

    # ==========================================================
    # Manager
    # ==========================================================

    objects = GatewayLogManager()
    
    
        # ===========================
    # Validation
    # ===========================

    def clean(self) -> None:
        """
        Validate GatewayLog invariants.

        This method is intentionally side-effect free.

        It:
            - Does not query the database.
            - Does not save the model.
            - Does not mutate the model.
            - Does not perform network operations.
            - Does not execute business workflows.
        """

        super().clean()

        if (
            self.attempt_id is None
            and self.refund_id is None
        ):
            raise ValidationError(
                _(
                    "Gateway log must belong to "
                    "a payment attempt or a refund."
                )
            )

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

        if self.request_method:
            normalized_method = (
                self.request_method.strip().upper()
            )

            if normalized_method != self.request_method:
                raise ValidationError(
                    {
                        "request_method": _(
                            "HTTP method must be normalized "
                            "to uppercase without surrounding whitespace."
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
                
        # ===========================
    # Persistence
    # ===========================

    def save(self, *args, **kwargs):
        """
        Persist the audit entity.

        GatewayLog is immutable.

        A persisted GatewayLog must never be updated through the normal
        model save API.

        Domain validation is always executed before persistence.
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

    # ===========================
    # Deletion Protection
    # ===========================

    def delete(self, *args, **kwargs):
        """
        Prevent deletion of gateway audit records.

        Gateway logs are historical audit records and must be retained.
        """

        raise ValidationError(
            _(
                "GatewayLog is immutable and cannot be deleted."
            )
        )

    # ===========================
    # Representation
    # ===========================

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
