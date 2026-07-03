# tests/performance/test_order_service_queries.py
import pytest

from django.test.utils import CaptureQueriesContext
from django.db import connection

from order.services.order import OrderService


pytestmark = pytest.mark.django_db


def test_create_order_query_count(
    user,
    address,
    cart,
):
    with CaptureQueriesContext(connection) as ctx:

        OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

    assert len(ctx) <= 15