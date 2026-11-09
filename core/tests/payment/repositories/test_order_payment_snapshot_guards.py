from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from payment.enums import PaymentGateway, PaymentStatusType
from payment.repositories.payment_repository import PaymentRepository
from tests.factories.order import OrderFactory
from tests.factories.payment import PaymentFactory


pytestmark = pytest.mark.django_db(transaction=True)


def test_payment_insert_requires_exact_order_payable_snapshot():
    order = OrderFactory()

    with pytest.raises(IntegrityError), transaction.atomic():
        PaymentRepository.create(
            order_id=order.pk,
            amount=order.payable_price + Decimal("1"),
            currency="IRR",
            gateway=PaymentGateway.ZARINPAL,
            status=PaymentStatusType.PENDING,
        )

    assert not order.payments.exists()


def test_payment_financial_identity_cannot_be_rewritten_by_queryset_update():
    order = OrderFactory()
    payment = PaymentFactory(order=order)

    with pytest.raises(IntegrityError), transaction.atomic():
        type(payment).objects.filter(pk=payment.pk).update(
            amount=payment.amount + Decimal("1"),
        )

    payment.refresh_from_db()
    assert payment.amount == order.payable_price


def test_payment_currency_and_order_identity_cannot_be_rewritten():
    order = OrderFactory()
    other_order = OrderFactory()
    payment = PaymentFactory(order=order)

    with pytest.raises(IntegrityError), transaction.atomic():
        type(payment).objects.filter(pk=payment.pk).update(currency="USD")

    with pytest.raises(IntegrityError), transaction.atomic():
        type(payment).objects.filter(pk=payment.pk).update(
            order_id=other_order.pk,
        )

    payment.refresh_from_db()
    assert payment.order_id == order.pk
    assert payment.currency == "IRR"


def test_payment_insert_rejects_non_contract_currency():
    order = OrderFactory()

    with pytest.raises(IntegrityError), transaction.atomic():
        PaymentRepository.create(
            order_id=order.pk,
            amount=order.payable_price,
            currency="USD",
            gateway=PaymentGateway.ZARINPAL,
            status=PaymentStatusType.PENDING,
        )

    assert not order.payments.exists()


def test_order_snapshot_arithmetic_is_enforced_on_insert():
    with pytest.raises(IntegrityError), transaction.atomic():
        OrderFactory(
            subtotal_price=Decimal("100000"),
            discount_amount=Decimal("10000"),
            shipping_price=Decimal("0"),
            tax_amount=Decimal("0"),
            payable_price=Decimal("95000"),
        )


def test_order_financial_snapshot_is_immutable_after_any_payment():
    order = OrderFactory()
    PaymentFactory(order=order, failed=True)

    with pytest.raises(IntegrityError), transaction.atomic():
        type(order).objects.filter(pk=order.pk).update(
            total_price=Decimal("100001"),
            subtotal_price=Decimal("100001"),
            payable_price=Decimal("100001"),
        )

    order.refresh_from_db()
    assert order.total_price == Decimal("100000")
    assert order.subtotal_price == Decimal("100000")
    assert order.payable_price == Decimal("100000")


@pytest.mark.parametrize(
    ("field", "payable_delta"),
    (
        ("discount_amount", -1),
        ("shipping_price", 1),
        ("tax_amount", 1),
    ),
)
def test_order_discount_shipping_and_tax_are_immutable_after_payment(
    field,
    payable_delta,
):
    order = OrderFactory()
    PaymentFactory(order=order, failed=True)

    with pytest.raises(IntegrityError), transaction.atomic():
        type(order).objects.filter(pk=order.pk).update(
            **{
                field: Decimal("1"),
                "payable_price": order.payable_price + payable_delta,
            }
        )

    order.refresh_from_db()
    assert getattr(order, field) == Decimal("0")
    assert order.payable_price == Decimal("100000")


def test_order_snapshot_can_be_corrected_before_first_payment():
    order = OrderFactory()

    updated = type(order).objects.filter(pk=order.pk).update(
        total_price=Decimal("110000"),
        subtotal_price=Decimal("110000"),
        discount_amount=Decimal("10000"),
        shipping_price=Decimal("5000"),
        tax_amount=Decimal("0"),
        payable_price=Decimal("105000"),
    )

    assert updated == 1
    order.refresh_from_db()
    assert order.payable_price == Decimal("105000")

    payment = PaymentRepository.create(
        order_id=order.pk,
        amount=Decimal("105000"),
        currency="IRR",
        gateway=PaymentGateway.ZARINPAL,
        status=PaymentStatusType.PENDING,
    )
    assert payment.amount == order.payable_price