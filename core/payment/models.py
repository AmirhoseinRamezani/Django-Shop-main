# # payments/models.py
# import uuid
# from django.core.validators import MinValueValidator
from django.db import models
# from django.conf import settings
# from django.db.models import JSONField
# from django.utils import timezone
# from django.utils.translation import gettext_lazy as _
# from django.db.models import Q
# from order.models import OrderStatusType
# from payment.managers import PaymentManager
# from payment.enums import PaymentStatusType ,PaymentGateway ,Currency
# from django.core.exceptions import ValidationError

    
#  class PaymentModel(models.Model):
   
#      idempotency_key = models.UUIDField(
#          unique=True,
#          editable=False,
#          default=uuid.uuid4,
#          # db_index=True,
#      )
   
#      order = models.ForeignKey(
#          "order.OrderModel",
#          on_delete=models.PROTECT,
#          related_name="payments",
#          null=True,
#          blank=True,
#      )
   
#      authority_id = models.CharField(
#          max_length=128,      
#          unique=True,
#          db_index=False,
#          # db_index=True,
#          editable=False,
#          help_text=_("Gateway authority / token"),
#      )
   
#      ref_id = models.CharField(
#          max_length=128,
#          # unique=False,
#          blank=True,
#          null=True,
#          db_index=True,
#      )
#      amount = models.DecimalField(
#          max_digits=12,
#          decimal_places=0,
#          validators=[MinValueValidator(1)],
#      )
#      gateway = models.CharField(
#          max_length=30,
#          choices=PaymentGateway.choices,
#          default=PaymentGateway.ZARINPAL,
#          db_index=True,
#      )
   
#      # response_json = JSONField(
#      #     default=dict,
#      #     blank=True,
#      #     help_text=_("Deprecated. Use response_payload."),
#      # )
#      # response_code = models.IntegerField(null=True, blank=True)
#      response_code = models.CharField(
#          max_length=32,
#          blank=True,
#          default="",
#      )
#      status = models.IntegerField(
#          choices=PaymentStatusType.choices,
#          default=PaymentStatusType.pending,
#      )
#      currency = models.CharField(
#          max_length=10,
#          choices=Currency.choices,
#          default=Currency.IRR,
#      )
#      created_date = models.DateTimeField(auto_now_add=True)
#      updated_date = models.DateTimeField(auto_now=True)
#      paid_date = models.DateTimeField(null=True, blank=True)
#      is_consumed = models.BooleanField(
#          default=False,
#          help_text=_("Used to finalize order (idempotency guard)"),
#      )
#      is_refunded = models.BooleanField(
#          default=False,
#          db_index=True,
#          help_text=_("Gateway refund completed."),
#      )
#      refund_date = models.DateTimeField(
#          null=True,
#          blank=True,
#      )
   
#      refund_ref_id = models.CharField(
#          max_length=255,
#          blank=True,
#          null=True,
#          db_index=True,
#      )
#      refunded_by = models.ForeignKey(
#          settings.AUTH_USER_MODEL,
#          null=True,
#          blank=True,
#          on_delete=models.SET_NULL,
#          related_name="processed_refunds",
#      )
   
#      request_payload = models.JSONField(
#          default=dict,
#          blank=True,
#          editable=False,
#      )
#      response_payload = models.JSONField(
#          default=dict,
#          blank=True,
#          editable=False
#      )
#      refund_request = models.JSONField(
#          default=dict,
#          blank=True,
#      )
#      refund_response = models.JSONField(
#          default=dict,
#          blank=True,
#      )
#      verified_date = models.DateTimeField(
#          null=True,
#          blank=True,
#      )
#      failure_reason = models.CharField(
#          max_length=255,
#          blank=True,
#      )
#      verification_attempts = models.PositiveSmallIntegerField(
#          default=0,
#      )
   
#      gateway_transaction_id = models.CharField(
#          max_length=128,
#          blank=True,
#          default="",
#          db_index=True,
#      )
#      gateway_message = models.CharField(
#          max_length=255,
#          blank=True,
#          default="",
#      )
#      meta = models.JSONField(
#          default=dict,
#          blank=True,
#      )
   
   
#      # Financial fields
#      # -------------------------------------
#      net_amount = models.DecimalField(
#          max_digits=12,
#          decimal_places=0,
#          default=0,
#          validators=[
#              MinValueValidator(0),
#          ],
#          help_text=_(
#              "Net amount received after provider and merchant fees."
#          ),
#      )
   
#      provider = models.CharField(
#          max_length=50,
#          blank=True,
#          default="",
#          db_index=True,
#          help_text=_(
#              "Actual payment provider used for this transaction."
#          ),
#      )
   
#      provider_fee = models.DecimalField(
#          max_digits=12,
#          decimal_places=0,
#          default=0,
#          validators=[
#              MinValueValidator(0),
#          ],
#          help_text=_(
#              "Fee charged by the payment provider."
#          ),
#      )
#      merchant_fee = models.DecimalField(
#          max_digits=12,
#          decimal_places=0,
#          default=0,
#          validators=[
#              MinValueValidator(0),
#          ],
#          help_text=_("Fee charged to the merchant."),
#      )
   
#      objects = PaymentManager()
   
#      class Meta:
#          ordering = ("-created_date",)
#          constraints = [
#              models.CheckConstraint(
#                  condition=(
#                      Q(is_consumed=False)
#                      |
#                      Q(status=PaymentStatusType.success)
#                  ),
#                  name="consumed_requires_success",
#              ),
#              models.CheckConstraint(
#                  condition=models.Q(amount__gt=0),
#                  name="payment_amount_positive",
#              ),
#              models.CheckConstraint(
#                  condition=(
#                      Q(is_refunded=False)
#                      |
#                      Q(refund_date__isnull=False)
#                  ),
#                  name="refund_date_exists",
#              ),
#              models.CheckConstraint(
#                  condition=(
#                      Q(verified_date__isnull=True)
#                      |
#                      Q(status=PaymentStatusType.success)
#                  ),
#                  name="verified_requires_success",
#              ),
#              models.CheckConstraint(
#                  condition=(
#                      Q(ref_id__isnull=True)
#                      |
#                      Q(status=PaymentStatusType.success)
#                  ),
#                  name="reference_requires_success",
#              ),
#              models.CheckConstraint(
#                  condition=(
#                      Q(refund_ref_id__isnull=True)
#                      |
#                      Q(is_refunded=True)
#                  ),
#                  name="refund_reference_requires_refund",
#              ),
#              models.CheckConstraint(
#                  condition=(
#                      Q(paid_date__isnull=True)
#                      |
#                      Q(status=PaymentStatusType.success)
#                  ),
#                  name="paid_date_requires_success",
#              ),
#              models.CheckConstraint(
#                  condition=(
#                      Q(gateway_transaction_id="")
#                      |
#                      Q(status=PaymentStatusType.success)
#                  ),
#                  name="gateway_transaction_requires_success",
#              ),
#              models.CheckConstraint(
#                  condition=(
#                      Q(refund_date__isnull=True)
#                      |
#                      Q(is_refunded=True)
#                  ),
#                  name="refund_flag_required",
#              ),
#              models.CheckConstraint(
#                  condition=Q(provider_fee__gte=0),
#                  name="payment_provider_fee_non_negative",
#              ),
#              models.CheckConstraint(
#                  condition=Q(merchant_fee__gte=0),
#                  name="payment_merchant_fee_non_negative",
#              ),
#              models.CheckConstraint(
#                  condition=(
#                      Q(
#                          is_refunded=False,
#                          refund_date__isnull=True,
#                      )
#                      |
#                      Q(
#                          is_refunded=True,
#                          refund_date__isnull=False,
#                      )
#                  ),
#                  name="payment_refund_state_consistent",
#              ),
#          ]
       
#          indexes = [
#              models.Index(fields=["status"]),
#              models.Index(fields=["order", "status"]),
#              models.Index(fields=["gateway","status"]),
#              models.Index(fields=["created_date"]),
#              models.Index(fields=["order","created_date"]),
#              models.Index(
#                  fields=[
#                      "order",
#                      "status",
#                      "-created_date",
#                  ]
#              ),
#              models.Index(
#                  fields=[
#                      "status",
#                      "created_date",
#                  ]
#              ),
#          ]
       
#      # ---------- Domain methods ----------
#      def mark_success(
#          self,
#          *,
#          ref_id,
#          gateway_transaction_id=None,
#          response=None,
#      ):
#          """
#          Mark payment as successfully verified.
#          Idempotency rules:
#          - Repeated success with the same ref_id is allowed.
#          - If gateway_transaction_id is already stored, a different
#          transaction id is rejected.
#          - A new gateway_transaction_id can be stored only when the
#          payment is being marked successful for the first time.
#          """
#          ref_id = str(ref_id)
#          if not ref_id:
#              raise ValidationError(
#                  _("Payment reference id is required.")
#              )
#          if gateway_transaction_id is not None:
#              gateway_transaction_id = str(
#                  gateway_transaction_id
#              ).strip()
#              if not gateway_transaction_id:
#                  gateway_transaction_id = None
#          # ---------------------------------------------------------
#          # Idempotent success
#          # ---------------------------------------------------------
#          if self.status == PaymentStatusType.success:
#              if self.ref_id != ref_id:
#                  raise ValidationError(_("Reference id mismatch."))
#              if (
#                  gateway_transaction_id is not None
#                  and self.gateway_transaction_id
#                  and self.gateway_transaction_id != gateway_transaction_id
#              ):
#                  raise ValidationError(_("Gateway transaction id mismatch."))
#              if (
#                  gateway_transaction_id is not None
#                  and not self.gateway_transaction_id
#              ):
#                  self.gateway_transaction_id = gateway_transaction_id
#                  self.save(
#                      update_fields=["gateway_transaction_id",]
#                  )
#              return self
#          # ---------------------------------------------------------
#          # Invalid state guards
#          # ---------------------------------------------------------
#          if self.is_refunded:
#              raise ValidationError(
#                  _("Refunded payment cannot be modified.")
#              )
#          if self.is_consumed:
#              raise ValidationError(
#                  _("Consumed payment cannot be modified.")
#              )
#          if not self.can_verify:
#              raise ValidationError(
#                  _("Payment cannot be verified.")
#              )
#          # ---------------------------------------------------------
#          # Success transition
#          # ---------------------------------------------------------
#          now = timezone.now()
#          self.status = PaymentStatusType.success
#          self.ref_id = ref_id
#          self.paid_date = now
#          if self.verified_date is None:
#              self.verified_date = now
#          self.failure_reason = ""
#          # Gateway transaction id is optional because not every
#          # gateway necessarily returns one.
#          if gateway_transaction_id is not None:
#              self.gateway_transaction_id = (
#                  gateway_transaction_id
#              )
#          # ---------------------------------------------------------
#          # Gateway response
#          # ---------------------------------------------------------
#          status_code = None
#          if response is not None:
#              status_code = (
#                  response.get("Status")
#                  or response.get("status")
#              )
#              self.response_payload = response
#              self.response_code = status_code
#          # ---------------------------------------------------------
#          # Verification attempt
#          # ---------------------------------------------------------
#          self.verification_attempts += 1
#          # ---------------------------------------------------------
#          # Persist only changed fields
#          # ---------------------------------------------------------
#          fields = [
#              "status",
#              "ref_id",
#              "paid_date",
#              "verified_date",
#              "failure_reason",
#              "verification_attempts",
#          ]
#          if gateway_transaction_id is not None:
#              fields.append(
#                  "gateway_transaction_id"
#              )
#          if response is not None:
#              fields.extend(
#                  [
#                      "response_payload",
#                      "response_code",
#                  ]
#              )
#          self.save(
#              update_fields=fields
#          )
#          return self
#      def mark_failed(
#          self,
#          *,
#          response=None,
#          reason=None,
#      ):
#          if self.is_refunded:
#              raise ValidationError(_("Refunded payment cannot be modified."))
#          if self.is_consumed:
#              raise ValidationError(_("Consumed payment cannot be modified."))
#          if self.status == PaymentStatusType.success:
#              raise ValidationError(_("Successful payment cannot become failed."))
#          if self.is_verified:
#              raise ValidationError(_("Verified payment cannot fail."))
#          self.status = PaymentStatusType.failed
#          fields=["status"]
#          if response is not None:
#              self.response_payload=response
#              self.response_code=(
#                  response.get("Status")
#                  or response.get("status")
#              )
#              fields.extend(
#                  [
#                      "response_payload",
#                      "response_code",
#                  ]
#              )
#          if reason:
#              self.failure_reason=reason
#              fields.append("failure_reason")
#          self.verification_attempts += 1
#          fields.append("verification_attempts")
#          self.save(
#              update_fields=fields
#          )
#          return self
       
#      def mark_refunded(
#          self,
#          *,
#          refund_ref_id=None,
#          refunded_by=None,
#          request=None,
#          response=None,
#      ):
#          if self.is_refunded:
#              raise ValidationError(_("Payment already refunded."))
#          if not self.is_consumed:
#              raise ValidationError(_("Only consumed successful payments can be refunded."))
#          if self.status != PaymentStatusType.success:
#              raise ValidationError(_("Only successful payments can be refunded."))
#          if self.ref_id is None:
#              raise ValidationError(_("Payment reference is missing."))
#          if self.paid_date is None:
#              raise ValidationError(_("Payment has not been verified."))
#          fields = [
#                  "is_refunded",
#                  "refund_date",
#                  "refund_ref_id",
#                  "refunded_by",
#                  "refund_response",
#                  "refund_request",
#              ]
#          if refund_ref_id:
#              self.refund_ref_id = str(
#                  refund_ref_id
#              ).strip()
#          self.is_refunded = True
#          self.refund_date = timezone.now()
#          self.refunded_by = refunded_by
#          self.refund_request = request or {}
#          self.refund_response = response or {}
#          self.save(update_fields=fields)
#          return self
   
#      def consume(self):
       
#          if not self.can_consume:
#             raise ValidationError(_("Payment cannot be consumed."))
       
#          # if self.status != PaymentStatusType.success:
#          #     raise ValidationError(_("Only successful payment can be consumed."))
#          # if self.is_refunded:
#          #     raise ValidationError(_("Payment already refunded."))
#          # if self.is_consumed:
#          #     raise ValidationError(_("Payment already consumed."))
#          self.is_consumed = True
       
#          self.save(
#              update_fields=[
#                  "is_consumed",
#              ]
#          )
#          return self
#      def clean(self):
       
#          # if self.amount <= 0:
#          #     raise ValidationError(
#          #         _("Amount must be greater than zero.")
#          #     )
#          # if self.refund_date and not self.is_refunded:
#          #     raise ValidationError(
#          #         _("Refund date without refund flag.")
#          #     )
       
#          if self.is_refunded:
#              if not self.is_success:
#                  raise ValidationError(_("Only successful payments can be refunded."))
#              # if not self.is_consumed and self.status != PaymentStatusType.success:
#              #     raise ValidationError(_("Only successful payments can be consumed."))
#              if not self.is_consumed:
#                  raise ValidationError(_("Refunded payment must be consumed."))
#          # if self.is_refunded and not self.is_success:
           
#          #     raise ValidationError(_("Only successful payments can be refunded."))
       
#          if self.refund_ref_id and not self.is_refunded:
#              raise ValidationError(_("Refund reference requires refunded payment."))
       
#          if self.verified_date and self.ref_id is None:
#              raise ValidationError(
#                  _("Verified payment requires reference id.")
#              )
           
#          if self.is_consumed and not self.is_success:
#              raise ValidationError(_("Only successful payments can be consumed."))
#          if (
#              self.status == PaymentStatusType.success
#              and self.net_amount
#              > self.amount
#          ):
#              raise ValidationError(_("Net amount cannot exceed payment amount."))
#          total_fees = (
#              self.provider_fee
#              + self.merchant_fee
#          )
#          if (
#              self.status == PaymentStatusType.success
#              and total_fees > self.amount
#          ):
#              raise ValidationError(_("Total payment fees cannot exceed payment amount."))
#          #     if self.status != PaymentStatusType.success:
#          #         raise ValidationError(_("refunded not success"))
#          # if self.is_consumed and self.status != PaymentStatusType.success:
#          #     raise ValidationError(_("Only successful payments can be consumed."))
           
#      def save(self,*args ,**kwargs):
#          if self.pk:
#              original = (
#                  self.__class__.objects
#                  .only(
#                      "authority_id",
#                      "idempotency_key",
#                  )
#                  .get(pk=self.pk)
#              )
#              if original.authority_id != self.authority_id:
#                  raise ValidationError(_("Authority id cannot be changed."))
           
#              if original.idempotency_key != self.idempotency_key:
#                  raise ValidationError(_("Idempotency key cannot be changed."))
       
#          self.full_clean()
       
#          return super().save(*args, **kwargs)
   
#      def __str__(self):
#          return f"Payment #{self.id} ({self.get_status_display()})"
   
#      # --------- Helpers ----------
#      # def get_gateway_reference(self):
#      #     return self.ref_id or self.authority_id
   
#      # ------- State Machine -------
#      @property
#      def is_open(self):
#          return (
#              self.status == PaymentStatusType.pending
#              and not self.is_consumed
#              and not self.is_refunded
#          )
       
#      @property
#      def can_refund(self):
#          return (
#              self.status == PaymentStatusType.success
#              and self.is_consumed
#              and not self.is_refunded
#              and self.ref_id is not None
#          )
#      @property
#      def is_pending(self):
#          return self.status == PaymentStatusType.pending
#      @property
#      def is_failed(self):
#          return self.status == PaymentStatusType.failed
#      @property
#      def is_success(self):
#          return self.status == PaymentStatusType.success
   
#      @property
#      def is_completed(self):
#          return (
#              self.is_success
#              and self.is_consumed
#              and not self.is_refunded
#          )
       
#      @property
#      def is_refundable(self):
#          return self.can_refund
   
#      @property
#      def can_verify(self):
#          return (
#              self.status == PaymentStatusType.pending
#              and self.ref_id is None
#              and self.verified_date is None
#              and not self.is_refunded
#          )
#      @property
#      def can_retry(self):
#          return (
#              self.status == PaymentStatusType.failed
#              and not self.is_refunded
#              and not self.is_consumed
#          )
       
#      @property
#      def can_consume(self):
#          return (
#              self.status == PaymentStatusType.success
#              and not self.is_consumed
#              and not self.is_refunded
#          )
#      @property
#      def is_verified(self):
#          return self.verified_date is not None
   
#      @property
#      def is_gateway_confirmed(self):
#          return (
#              self.ref_id is not None
#              and self.verified_date is not None
#          )
#      @property
#      def is_finalized(self):
#          return (
#              self.is_consumed
#              or self.is_refunded
#          )
       
#      @property
#      def has_reference(self):
#          return self.ref_id is not None
#          # return bool(self.ref_id)
#      @property
#      def gateway_name(self):
#          return self.get_gateway_display()
   
   
#      @property
#      def gateway_reference(self):
#          return self.gateway_transaction_id or self.ref_id or self.authority_id
   
   
#      # @property
#      # def is_closed(self):
#      #     return (
#      #         self.is_refunded
#      #         or self.is_completed
#      #         or (
#      #             self.is_failed
#      #             and not self.order.can_retry_payment()
#      #         )
#      #     )
   
#      # @property
#      # def latest_gateway_reference(self):
#      #     return (
#      #         self.refund_ref_id
#      #         or self.ref_id
#      #         or self.authority_id
#      #     )
   
#      # @property
#      # def lifecycle(self):
#      #     if self.is_refunded:
#      #         return "refunded"
#      #     if self.is_completed:
#      #         return "completed"
#      #     if self.is_failed:
#      #         return "failed"
#      #     if self.is_pending:
#      #         return "pending"
#      #     return "unknown"
   