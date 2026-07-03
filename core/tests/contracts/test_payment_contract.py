# tests/contracts/test_payment_contract.py
import pytest

from payment.models import PaymentStatusType


pytestmark = pytest.mark.django_db


def test_payment_status_values_unique():

    values = [item.value for item in PaymentStatusType]

    assert len(values) == len(set(values))