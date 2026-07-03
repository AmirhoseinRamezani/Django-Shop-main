# tests/performance/test_n_plus_one.py
import pytest

from django.db import connection
from django.test.utils import CaptureQueriesContext

from order.models import OrderModel


pytestmark = [
    pytest.mark.django_db,
    pytest.mark.performance,
]


class TestNPlusOne:

    def test_orders_prefetch_items(
        self,
        order_factory,
    ):
        order_factory.create_batch(10)

        with CaptureQueriesContext(connection) as queries:

            list(
                OrderModel.objects
                .prefetch_related(
                    "order_items",
                )
            )

        assert len(queries) <= 2