# tests/concurrency/test_stock_race.py
import pytest

from tests.concurrency.base import (
    ConcurrentRunner,
)

from order.services.order import (
    OrderService,
)


pytestmark = pytest.mark.django_db(
    transaction=True,
)


def test_stock_locking(
    order_builder,
):

    scenario = order_builder.build()

    runner = ConcurrentRunner()

    runner.run(

        lambda: OrderService.create_online_order(
            **scenario,
        ),

        lambda: OrderService.create_online_order(
            **scenario,
        ),
    )
