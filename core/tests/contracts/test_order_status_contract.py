# tests/contracts/test_order_status_contract.py
import pytest

from order.models import OrderStatusType


pytestmark = pytest.mark.django_db


def test_order_status_values_unique():

    values = [i.value for i in OrderStatusType]

    assert len(values) == len(set(values))