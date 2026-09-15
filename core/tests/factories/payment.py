# core/tests/factories/payment.py
import factory
from django.utils import timezone

from payment.models import GatewayLog, PaymentAttempt, PaymentModel, Refund
from payment.enums import (
    Currency,
    PaymentGateway,
    PaymentStatusType,
    PaymentAttemptStatus,
    GatewayLogType,
    GatewayLogDirection,
    RefundStatus,
    RefundReason,
)

from tests.factories.base import BaseFactory
from tests.factories.order import OrderFactory


class PaymentFactory(BaseFactory):
    """
    Factory for PaymentModel aggregate root.
    Only manages aggregate state (order, amount, status, version, flags).
    No gateway execution details here!
    """

    class Meta:
        model = PaymentModel

    order = factory.SubFactory(OrderFactory)
    amount = factory.LazyAttribute(
        lambda o: o.order.payable_price if getattr(o.order, "payable_price", 0) > 0 else 1000
    )
    currency = Currency.IRR
    gateway = PaymentGateway.ZARINPAL
    status = PaymentStatusType.PENDING
    version = 1
    is_consumed = False
    is_refunded = False

    class Params:
        success = factory.Trait(
            status=PaymentStatusType.SUCCESS,
        )
        failed = factory.Trait(
            status=PaymentStatusType.FAILED,
        )
        consumed = factory.Trait(
            status=PaymentStatusType.SUCCESS,
            is_consumed=True,
        )
        refunded = factory.Trait(
            status=PaymentStatusType.SUCCESS,
            is_consumed=True,
            is_refunded=True,
        )


class PaymentAttemptFactory(BaseFactory):
    """
    Factory for PaymentAttempt (Individual gateway execution lifecycle).
    Holds authority_id, reference, transaction ids, status, timing.
    """

    class Meta:
        model = PaymentAttempt

    payment = factory.SubFactory(PaymentFactory)
    attempt_number = 1
    authority_id = ""
    gateway_reference = ""
    gateway_transaction_id = ""
    retry_of = None
    retry_count = 1
    status = PaymentAttemptStatus.PENDING
    response_code = ""
    gateway_message = ""
    failure_reason = ""
    latency_ms = None
    ip_address = "127.0.0.1"
    user_agent = "pytest"
    meta = factory.LazyFunction(dict)

    class Params:
        success = factory.Trait(
            status=PaymentAttemptStatus.SUCCESS,
            authority_id=factory.Sequence(lambda n: f"AUTH-{n:08d}"),
            gateway_reference=factory.Sequence(lambda n: f"REF-{n:08d}"),
            gateway_transaction_id=factory.Sequence(lambda n: f"TXN-{n:08d}"),
            response_code="100",
            gateway_message="Payment successful",
            failure_reason="",
            latency_ms=120,
        )
        failed = factory.Trait(
            status=PaymentAttemptStatus.FAILED,
            failure_reason="Gateway payment failed",
            response_code="-1",
            gateway_message="Payment failed",
            latency_ms=250,
        )
        timeout = factory.Trait(
            status=PaymentAttemptStatus.TIMEOUT,
            failure_reason="Gateway timeout",
            latency_ms=5000,
        )

        cancelled = factory.Trait(
            status=PaymentAttemptStatus.CANCELLED,
            failure_reason="Payment attempt cancelled",
            latency_ms=100,
        )

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        status = kwargs.get(
            "status",
            PaymentAttemptStatus.PENDING,
        )

        if status == PaymentAttemptStatus.PENDING:
            return super()._create(
                model_class,
                *args,
                **kwargs,
            )

        # Terminal attempts must be inserted directly because the database
        # intentionally allows only one pending attempt per Payment.
        terminal_kwargs = dict(kwargs)
        terminal_kwargs["finished_at"] = timezone.now()

        return super()._create(
            model_class,
            *args,
            **terminal_kwargs,
        )


class GatewayLogFactory(BaseFactory):
    """
    Factory for raw Gateway HTTP payload logs.
    """

    class Meta:
        model = GatewayLog

    attempt = factory.SubFactory(PaymentAttemptFactory)
    request_url = "https://api.zarinpal.com/pg/v4/payment/request.json"

    gateway = PaymentGateway.ZARINPAL
    log_type = GatewayLogType.REQUEST
    direction = GatewayLogDirection.OUTBOUND

    request_method = "POST"
    http_status = 200
    latency_ms = 120
    request_headers = factory.LazyFunction(dict)
    request_payload = factory.LazyFunction(dict)
    response_headers = factory.LazyFunction(dict)
    response_payload = factory.LazyFunction(dict)
    response_code = ""
    gateway_message = ""


class RefundFactory(BaseFactory):
    """
    Factory for Refund.
    """

    class Meta:
        model = Refund

    payment = factory.SubFactory(PaymentFactory)
    amount = factory.LazyAttribute(lambda o: o.payment.amount)
    reason = RefundReason.CUSTOMER_REQUEST
    status = RefundStatus.PENDING
    gateway_reference = ""
    gateway_transaction_id = ""
    response_code = ""
    gateway_message = ""
    failure_reason = ""
    latency_ms = None
    requested_at = factory.LazyFunction(timezone.now)
    finished_at = None

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        requested_status = kwargs.get(
            "status",
            RefundStatus.PENDING,
        )

        if requested_status == RefundStatus.PENDING:
            return super()._create(
                model_class,
                *args,
                **kwargs,
            )

        terminal_kwargs = dict(kwargs)
        terminal_kwargs["status"] = RefundStatus.PENDING
        terminal_kwargs["finished_at"] = None

        obj = super()._create(
            model_class,
            *args,
            **terminal_kwargs,
        )

        if requested_status == RefundStatus.SUCCESS:
            obj.mark_success(
                gateway_reference=obj.gateway_reference,
                gateway_transaction_id=obj.gateway_transaction_id,
                response_code=obj.response_code,
                gateway_message=obj.gateway_message,
                latency_ms=obj.latency_ms,
            )
        elif requested_status == RefundStatus.FAILED:
            obj.mark_failed(
                reason=obj.failure_reason,
                response_code=obj.response_code,
                gateway_message=obj.gateway_message,
                latency_ms=obj.latency_ms,
            )
        else:
            raise ValueError(
                f"Unsupported RefundFactory terminal status: {requested_status}"
            )

        obj.save()
        return obj
