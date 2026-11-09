from __future__ import annotations

import threading

import pytest
from django.db import IntegrityError, close_old_connections, connection, connections, transaction
from django.db.models import F

from order.models import OrderModel
from payment.enums import PaymentGateway, PaymentStatusType
from payment.repositories.payment_repository import PaymentRepository
from tests.factories.order import OrderFactory


pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="Financial snapshot concurrency requires PostgreSQL row locks.",
    ),
]


def test_payment_creation_races_with_order_snapshot_update_without_divergence():
    order = OrderFactory()
    original_amount = order.payable_price
    barrier = threading.Barrier(2)
    outcomes: dict[str, str] = {}
    errors: list[BaseException] = []
    outcomes_lock = threading.Lock()

    def record(name: str, value: str) -> None:
        with outcomes_lock:
            outcomes[name] = value

    def create_payment() -> None:
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            with transaction.atomic():
                PaymentRepository.create(
                    order_id=order.pk,
                    amount=original_amount,
                    currency="IRR",
                    gateway=PaymentGateway.ZARINPAL,
                    status=PaymentStatusType.PENDING,
                )
            record("payment", "created")
        except IntegrityError:
            record("payment", "rejected")
        except BaseException as exc:
            errors.append(exc)
        finally:
            connections.close_all()

    def update_order_snapshot() -> None:
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            with transaction.atomic():
                OrderModel.objects.filter(pk=order.pk).update(
                    total_price=F("total_price") + 1,
                    subtotal_price=F("subtotal_price") + 1,
                    payable_price=F("payable_price") + 1,
                )
            record("order", "updated")
        except IntegrityError:
            record("order", "rejected")
        except BaseException as exc:
            errors.append(exc)
        finally:
            connections.close_all()

    workers = [
        threading.Thread(target=create_payment),
        threading.Thread(target=update_order_snapshot),
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=20)

    assert all(not worker.is_alive() for worker in workers)
    assert errors == []
    assert outcomes in (
        {"payment": "created", "order": "rejected"},
        {"payment": "rejected", "order": "updated"},
    )

    order.refresh_from_db()
    payment = order.payments.first()

    if payment is not None:
        assert outcomes["payment"] == "created"
        assert outcomes["order"] == "rejected"
        assert payment.amount == order.payable_price == original_amount
    else:
        assert outcomes["payment"] == "rejected"
        assert outcomes["order"] == "updated"
        assert order.payable_price == original_amount + 1